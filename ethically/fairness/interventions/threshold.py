"""
Post-processing fairness intervension by choosing thresholds.

There are multiple definitions for choosing the thresholds:

1. Single threshold for all the sensitive attribute values
   that minimizes cost.
2. A threshold for each sensitive attribute value
   that minimize cost.
3. A threshold for each sensitive attribute value
   that achieve independence and minimize cost.
4. A threshold for each sensitive attribute value
   that achieve equal FNR (equal opportunity) and minimize cost.
5. A threshold for each sensitive attribute value
   that achieve seperation (equalized odds) and minimize cost.

The code is based on `fairmlbook repository <https://github.com/fairmlbook/fairmlbook.github.io>`_.

References:
    - Hardt, M., Price, E., & Srebro, N. (2016).
      Equality of opportunity in supervised learning.
      In Advances in neural information processing systems
      (pp. 3315-3323).
    - `Attacking discrimination with
      smarter machine learning by Google
      <https://research.google.com/bigpicture/attacking-discrimination-in-ml/>`_.

"""

# pylint: disable=no-name-in-module

import matplotlib.pylab as plt
import numpy as np
import pandas as pd
from scipy.spatial import Delaunay

from ethically.fairness.metrics.visualization import plot_roc_curves


def _ternary_search_float(f, left, right, tol):
    """Trinary search: minimize f(x) over [left, right], to within +/-tol in x.

    Works assuming f is quasiconvex.

    """
    while right - left > tol:
        left_third = (2 * left + right) / 3
        right_third = (left + 2 * right) / 3
        if f(left_third) < f(right_third):
            right = right_third
        else:
            left = left_third
    return (right + left) / 2


def _ternary_search_domain(f, domain):
    """Trinary search: minimize f(x) over a domain (sequence).

    Works assuming f is quasiconvex and domain is ascending sorted.

    """
    left = 0
    right = len(domain) - 1
    changed = True

    while changed and left != right:

        changed = False

        left_third = (2 * left + right) // 3
        right_third = (left + 2 * right) // 3

        if f(domain[left_third]) < f(domain[right_third]):
            right = right_third - 1
            changed = True
        else:
            left = left_third + 1
            changed = True

    return domain[(left + right) // 2]


def _cost_function(fpr, tpr, base_rate, cost_matrix):
    """Compute the cost of given (fpr, tpr).

    [[tn, fp], [fn, tp]]
    """

    fp = fpr * (1 - base_rate)
    tn = (1 - base_rate) - fp
    tp = tpr * base_rate
    fn = base_rate - tp

    conf_matrix = np.array([tn, fp, fn, tp])

    return (conf_matrix * np.array(cost_matrix).ravel()).sum()


def _extract_threshold(roc_curves):
    return next(iter(roc_curves.values()))[2]


def _first_index_above(array, value):
    """Find the smallest index i for which array[i] > value.

    If no such value exists, return len(array).
    """
    array = np.array(array)
    v = np.concatenate([array > value, np.ones_like(array[-1:])])
    return np.argmax(v, axis=0)


def _calc_acceptance_rate(fpr, tpr, base_rate):
    return 1 - ((fpr * (1 - base_rate)
                 + tpr * base_rate))


def find_single_threshold(roc_curves, base_rates, proportions,
                          cost_matrix):
    """Compute single threshold that minimizes cost.

    :param roc_curves: Receiver operating characteristic (ROC)
                       by attribute.
    :type roc_curves: dict
    :param base_rates: Base rate by attribute.
    :type base_rates: dict
    :param proportions: Proportion of each attribute value.
    :type proportions: dict
    :param cost_matrix: Cost matrix by [[tn, fp], [fn, tp]].
    :type cost_matrix: sequence
    :return: Threshold, FPR and TPR by attribute and cost value.
    :rtype: tuple

    """

    def total_cost_function(index):
        total_cost = 0

        for group, roc in roc_curves.items():
            fpr = roc[0][index]
            tpr = roc[1][index]

            group_cost = _cost_function(fpr, tpr,
                                        base_rates[group], cost_matrix)
            group_cost *= proportions[group]

            total_cost += group_cost

        return -total_cost

    thresholds = _extract_threshold(roc_curves)

    cutoff_index = _ternary_search_domain(total_cost_function,
                                          range(len(thresholds)))

    fpr_tpr = {group: (roc[0][cutoff_index], roc[1][cutoff_index])
               for group, roc in roc_curves.items()}

    cost = total_cost_function(cutoff_index)

    return thresholds[cutoff_index], fpr_tpr, cost


def find_min_cost_thresholds(roc_curves, base_rates, cost_matrix):
    """Compute thresholds by attribute values that minimize cost.

    :param roc_curves: Receiver operating characteristic (ROC)
                       by attribute.
    :type roc_curves: dict
    :param base_rates: Base rate by attribute.
    :type base_rates: dict
    :param cost_matrix: Cost matrix by [[tn, fp], [fn, tp]].
    :type cost_matrix: sequence
    :return: Thresholds, FPR and TPR by attribute and cost value.
    :rtype: tuple

    """
    # pylint: disable=cell-var-from-loop

    cutoffs = {}
    fpr_tpr = {}

    cost = 0
    thresholds = _extract_threshold(roc_curves)

    for group, roc in roc_curves.items():
        def group_cost_function(index):
            fpr = roc[0][index]
            tpr = roc[1][index]
            return -_cost_function(fpr, tpr,
                                   base_rates[group], cost_matrix)

        threshold_index = _ternary_search_domain(group_cost_function,
                                                 range(len(thresholds)))

        cutoffs[group] = thresholds[threshold_index]

        fpr_tpr[group] = (roc[0][threshold_index],
                          roc[1][threshold_index])

        cost += group_cost_function(threshold_index)

    return cutoffs, fpr_tpr, cost


def get_acceptance_rate_indices(roc_curves, base_rates,
                                acceptance_rate_value):
    indices = {}
    for group, roc in roc_curves.items():
        # can be calculated outside the function
        acceptance_rates = _calc_acceptance_rate(fpr=roc[0],
                                                 tpr=roc[1],
                                                 base_rate=base_rates[group])

        index = _first_index_above(acceptance_rates,
                                   (1 - acceptance_rate_value)) - 2

        indices[group] = index

    return indices


def find_independence_thresholds(roc_curves, base_rates, proportions,
                                 cost_matrix):
    """Compute thresholds that achieve independence and minimize cost.

    :param roc_curves: Receiver operating characteristic (ROC)
                       by attribute.
    :type roc_curves: dict
    :param base_rates: Base rate by attribute.
    :type base_rates: dict
    :param proportions: Proportion of each attribute value.
    :type proportions: dict
    :param cost_matrix: Cost matrix by [[tn, fp], [fn, tp]].
    :type cost_matrix: sequence
    :return: Thresholds, FPR and TPR by attribute and cost value.
    :rtype: tuple

    """

    cutoffs = {}

    def total_cost_function(acceptance_rate_value):
        # todo: move demo here + multiple cost
        indices = get_acceptance_rate_indices(roc_curves, base_rates,
                                              acceptance_rate_value)

        total_cost = 0

        for group, roc in roc_curves.items():
            index = indices[group]

            fpr = roc[0][index]
            tpr = roc[1][index]

            group_cost = _cost_function(fpr, tpr,
                                        base_rates[group],
                                        cost_matrix)
            group_cost *= proportions[group]

            total_cost += group_cost

        return -total_cost

    acceptance_rate_min_cost = _ternary_search_float(total_cost_function,
                                                     0, 1, 1e-3)
    threshold_indices = get_acceptance_rate_indices(roc_curves, base_rates,
                                                    acceptance_rate_min_cost)

    thresholds = _extract_threshold(roc_curves)

    cutoffs = {group: thresholds[threshold_index]
               for group, threshold_index
               in threshold_indices.items()}

    fpr_tpr = {group: (roc[0][threshold_indices[group]],
                       roc[1][threshold_indices[group]])
               for group, roc in roc_curves.items()}

    return cutoffs, fpr_tpr, acceptance_rate_min_cost


def get_fnr_indices(roc_curves, fnr_value):
    indices = {}
    for group, roc in roc_curves.items():
        tprs = roc[1]
        index = _first_index_above(1 - tprs,
                                   (1 - fnr_value)) - 1

        indices[group] = index

    return indices


def find_fnr_thresholds(roc_curves, base_rates, proportions,
                        cost_matrix):
    """Compute thresholds that achieve equal FNRs and minimize cost.

    Also known as **equal opportunity**.

    :param roc_curves: Receiver operating characteristic (ROC)
                       by attribute.
    :type roc_curves: dict
    :param base_rates: Base rate by attribute.
    :type base_rates: dict
    :param proportions: Proportion of each attribute value.
    :type proportions: dict
    :param cost_matrix: Cost matrix by [[tn, fp], [fn, tp]].
    :type cost_matrix: sequence
    :return: Thresholds, FPR and TPR by attribute and cost value.
    :rtype: tuple

    """

    cutoffs = {}

    def total_cost_function(fnr_value):
        # todo: move demo here + multiple cost
        indices = get_fnr_indices(roc_curves, fnr_value)

        total_cost = 0

        for group, roc in roc_curves.items():
            index = indices[group]

            fpr = roc[0][index]
            tpr = roc[1][index]

            group_cost = _cost_function(fpr, tpr,
                                        base_rates[group],
                                        cost_matrix)
            group_cost *= proportions[group]

            total_cost += group_cost

        return -total_cost

    fnr_value_min_cost = _ternary_search_float(total_cost_function,
                                               0, 1, 1e-3)
    threshold_indices = get_fnr_indices(roc_curves, fnr_value_min_cost)

    cost = total_cost_function(fnr_value_min_cost)

    fpr_tpr = {group: (roc[0][threshold_indices[group]],
                       roc[1][threshold_indices[group]])
               for group, roc in roc_curves.items()}

    thresholds = _extract_threshold(roc_curves)
    cutoffs = {group: thresholds[threshold_index]
               for group, threshold_index
               in threshold_indices.items()}

    return cutoffs, fpr_tpr, cost, fnr_value_min_cost


def _find_feasible_roc(roc_curves):
    polygons = [Delaunay(list(zip(fprs, tprs)))
                for group, (fprs, tprs, _) in roc_curves.items()]

    feasible_points = []

    for poly in polygons:
        for p in poly.points:

            if all(poly2.find_simplex(p) != -1 for poly2 in polygons):
                feasible_points.append(p)

    return np.array(feasible_points)


def find_separation_thresholds(roc_curves, base_rate, cost_matrix):
    """Compute thresholds that achieve separation and minimize cost.

    Also known as **equalized odds**.

    :param roc_curves: Receiver operating characteristic (ROC)
                       by attribute.
    :type roc_curves: dict
    :param base_rate: Overall base rate.
    :type base_rate: float
    :param cost_matrix: Cost matrix by [[tn, fp], [fn, tp]].
    :type cost_matrix: sequence
    :return: Thresholds, FPR and TPR by attribute and cost value.
    :rtype: tuple

    """

    feasible_points = _find_feasible_roc(roc_curves)

    cost, (best_fpr, best_tpr) = max((_cost_function(fpr, tpr, base_rate,
                                                     cost_matrix),
                                      (fpr, tpr))
                                     for fpr, tpr in feasible_points)

    return {}, {'': (best_fpr, best_tpr)}, cost


def find_thresholds(roc_curves, proportions, base_rate,
                    base_rates, cost_matrix,
                    with_single=True, with_min_cost=True,
                    with_independence=True, with_fnr=True,
                    with_separation=True):
    """Compute thresholds that achieve various criteria and minimize cost.

    :param roc_curves: Receiver operating characteristic (ROC)
                       by attribute.
    :type roc_curves: dict
    :param proportions: Proportion of each attribute value.
    :type proportions: dict
    :param base_rate: Overall base rate.
    :type base_rate: float
    :param base_rates: Base rate by attribute.
    :type base_rates: dict
    :param cost_matrix: Cost matrix by [[tn, fp], [fn, tp]].
    :type cost_matrix: sequence

    :param with_single: Compute single threshold.
    :type with_single: bool
    :param with_min_cost: Compute minimum cost thresholds.
    :type with_min_cost: bool
    :param with_independence: Compute independence thresholds.
    :type with_independence: bool
    :param with_fnr: Compute FNR thresholds.
    :type with_fnr: bool
    :param with_separation: Compute separation thresholds.
    :type with_separation: bool

    :return: Dictionary of threshold criteria,
             and for each criterion:
             thresholds, FPR and TPR by attribute and cost value.
    :rtype: dict

    """

    thresholds = {}

    if with_single:
        thresholds['single'] = find_single_threshold(roc_curves,
                                                     base_rates,
                                                     proportions,
                                                     cost_matrix)

    if with_min_cost:
        thresholds['min_cost'] = find_min_cost_thresholds(roc_curves,
                                                          base_rates,
                                                          cost_matrix)

    if with_independence:
        thresholds['independence'] = find_independence_thresholds(roc_curves,
                                                                  base_rates,
                                                                  proportions,
                                                                  cost_matrix)

    if with_fnr:
        thresholds['fnr'] = find_fnr_thresholds(roc_curves,
                                                base_rates,
                                                proportions,
                                                cost_matrix)

    if with_separation:
        thresholds['separation'] = find_separation_thresholds(roc_curves,
                                                              base_rate,
                                                              cost_matrix)

    return thresholds


def plot_roc_curves_thresholds(roc_curves, thresholds_data,
                               aucs=None,
                               title='ROC Curves by Attribute',
                               ax=None, figsize=None,
                               title_fontsize='large',
                               text_fontsize='medium'):
    """Generate the ROC curves by attribute with thresholds.

    Based on :func:`skplt.metrics.plot_roc`

    :param roc_curves: Receiver operating characteristic (ROC)
                       by attribute.
    :type roc_curves: dict
    :param thresholds_data: Thresholds by attribute from the
                            function
                            :func:`~ethically.interventions
                            .threshold.find_thresholds`.
    :type thresholds_data: dict
    :param aucs: Area Under the ROC (AUC) by attribute.
    :type aucs: dict
    :param str title: Title of the generated plot.
    :param ax: The axes upon which to plot the curve.
               If `None`, the plot is drawn on a new set of axes.
    :param tuple figsize: Tuple denoting figure size of the plot
                          e.g. (6, 6).
    :param title_fontsize: Matplotlib-style fontsizes.
                          Use e.g. 'small', 'medium', 'large'
                          or integer-values.
    :param text_fontsize: Matplotlib-style fontsizes.
                          Use e.g. 'small', 'medium', 'large'
                          or integer-values.
    :return: The axes on which the plot was drawn.
    :rtype: :class:`matplotlib.axes.Axes`

    """

    ax = plot_roc_curves(roc_curves, aucs,
                         title, ax, figsize, title_fontsize, text_fontsize)

    MARKERS = ['o', '^', 'x', '+', 'p']

    for (name, data), marker in zip(thresholds_data.items(), MARKERS):
        label = name.replace('_', ' ').title()
        ax.scatter(*zip(*data[1].values()),
                   marker=marker, color='k', label=label,
                   zorder=float('inf'))

    plt.legend()

    return ax


def plot_fpt_tpr(roc_curves,
                 title='FPR-TPR Curves by Attribute',
                 ax=None, figsize=None,
                 title_fontsize='large', text_fontsize='medium'):
    """Generate FPR and TPR curves by thresholds and by attribute.

    Based on :func:`skplt.metrics.plot_roc`

    :param roc_curves: Receiver operating characteristic (ROC)
                       by attribute.
    :type roc_curves: dict
    :param str title: Title of the generated plot.
    :param ax: The axes upon which to plot the curve.
               If `None`, the plot is drawn on a new set of axes.
    :param tuple figsize: Tuple denoting figure size of the plot
                          e.g. (6, 6).
    :param title_fontsize: Matplotlib-style fontsizes.
                          Use e.g. 'small', 'medium', 'large'
                          or integer-values.
    :param text_fontsize: Matplotlib-style fontsizes.
                          Use e.g. 'small', 'medium', 'large'
                          or integer-values.
    :return: The axes on which the plot was drawn.
    :rtype: :class:`matplotlib.axes.Axes`

    """

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)  # pylint: disable=unused-variable

    ax.set_title(title, fontsize=title_fontsize)

    thresholds = _extract_threshold(roc_curves)

    prop_cycle = plt.rcParams['axes.prop_cycle']
    colors = prop_cycle.by_key()['color']

    for (group, roc), color in zip(roc_curves.items(), colors):
        plt.plot(thresholds, roc[0], '-',
                 label='{} - FPR'.format(group), color=color)
        plt.plot(thresholds, roc[1], '--',
                 label='{} - TPR'.format(group), color=color)
        plt.legend()

    ax.set_ylim([0.0, 1.05])
    ax.set_xlabel('Threshold', fontsize=text_fontsize)
    ax.set_ylabel('Probability', fontsize=text_fontsize)
    ax.tick_params(labelsize=text_fontsize)
    ax.legend(fontsize=text_fontsize)

    return ax


def plot_costs(thresholds_data,
               title='Cost by Threshold',
               ax=None, figsize=None,
               title_fontsize='large', text_fontsize='medium'):
    """Plot cost by threshold definition and by attribute.

    Based on :func:`skplt.metrics.plot_roc`

    :param thresholds_data: Thresholds by attribute from the
                            function
                            :func:`~ethically.interventions
                            .threshold.find_thresholds`.
    :type thresholds_data: dict
    :param str title: Title of the generated plot.
    :param ax: The axes upon which to plot the curve.
               If `None`, the plot is drawn on a new set of axes.
    :param tuple figsize: Tuple denoting figure size of the plot
                          e.g. (6, 6).
    :param title_fontsize: Matplotlib-style fontsizes.
                          Use e.g. 'small', 'medium', 'large'
                          or integer-values.
    :param text_fontsize: Matplotlib-style fontsizes.
                          Use e.g. 'small', 'medium', 'large'
                          or integer-values.
    :return: The axes on which the plot was drawn.
    :rtype: :class:`matplotlib.axes.Axes`

    """

    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=figsize)  # pylint: disable=unused-variable

    ax.set_title(title, fontsize=title_fontsize)

    costs = {group.replace('_', ' ').title(): cost
             for group, (_, _, cost, *_) in thresholds_data.items()}

    (pd.Series(costs)
     .sort_values(ascending=False)
     .plot(kind='barh', ax=ax))

    ax.set_xlabel('Cost', fontsize=text_fontsize)
    ax.set_ylabel('Threshold', fontsize=text_fontsize)
    ax.tick_params(labelsize=text_fontsize)

    return ax

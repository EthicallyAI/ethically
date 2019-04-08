"""
Metrics and debiasing for bias (such as gender and race) in words embedding.

.. warning::
    The following paper argues that the current methods
    have an only superficial effect on the bias in words embedding:

    Gonen, H., & Goldberg, Y. (2019).
    `Lipstick on a Pig:
    Debiasing Methods Cover up Systematic Gender Biases
    in Word Embeddings But do not Remove Them <https://arxiv.org/abs/1903.03862>`_.
    arXiv preprint arXiv:1903.03862.

Currently, two methods are supported:

1. Bolukbasi et al. (2016) Bias Measure and Debiasing
2. WEAT Measure

Besides, some of the standard benchmarks for
words embeddings are also available, primarily to check
the impact of debiasing performance.

"""

from .bias import BiasWordsEmbedding, GenderBiasWE
from .data import load_w2v_small
from .weat import (
    calc_all_weat, calc_single_weat, calc_weat_pleasant_unpleasant_attribute,
)

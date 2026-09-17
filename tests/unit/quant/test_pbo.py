"""The overfitting probability, and the fixture trap that would make it lie."""

import numpy as np
import pytest

import automatron_quant as quant
from tests.unit.quant.test_dsr import build_matrix, store


@pytest.fixture(scope="module", autouse=True)
def samples():
    quant.ensure_samples()


def load(sample_name):
    return quant.load_returns_matrix.invoke({"sample_name": sample_name})["returns_id"]


def test_pure_noise_sample_scores_as_overfit():
    """The bundled noise matrix is the worked example of the failure mode."""
    result = quant.pbo_cscv.invoke({"returns_id": load("returns_noise")})
    assert result["pbo"] >= 0.4, "the bundled noise sample must demonstrate overfitting"
    assert result["pbo"] > quant.PBO_FAIL
    assert result["splits_evaluated"] == 924  # C(12, 6)
    assert result["performance_degradation_slope"] < 0


def test_planted_edge_scores_lower_than_noise():
    """A real edge survives the split better than noise does."""
    noise = quant.pbo_cscv.invoke({"returns_id": load("returns_noise")})["pbo"]
    edge = quant.pbo_cscv.invoke({"returns_id": load("returns_planted_edge")})["pbo"]
    assert edge < noise


def test_full_sample_demeaning_forces_a_meaningless_one():
    """Guards the fixture, not the algorithm.

    If every column sums to zero and the split is balanced, each column's two halves
    are exactly anti-correlated, so the in-sample winner is forced to be the
    out-of-sample loser and the probability reads 1.0 for a reason that has nothing
    to do with overfitting. Demeaned noise must never be used as a fixture, and this
    records why.
    """
    matrix = build_matrix(3)
    matrix = matrix - matrix.mean(axis=0, keepdims=True)
    result = quant.pbo_cscv.invoke({"returns_id": store(matrix)})
    assert result["pbo"] == 1.0

    half = matrix.shape[0] // 2
    correlation = np.corrcoef(matrix[:half].mean(axis=0), matrix[half:].mean(axis=0))[0, 1]
    assert correlation == pytest.approx(-1.0, abs=1e-9)


def test_verdict_rules_follow_the_thresholds():
    below = quant.verdict.invoke({"dsr": 0.99, "pbo": 0.80, "wf_positive_share": 0.9})
    assert below["level"] == "LIKELY_OVERFIT"

    weak = quant.verdict.invoke({"dsr": 0.20, "pbo": 0.05, "wf_positive_share": 0.9})
    assert weak["level"] == "LIKELY_OVERFIT"

    strong = quant.verdict.invoke({"dsr": 0.97, "pbo": 0.10, "wf_positive_share": 0.8})
    assert strong["level"] == "EVIDENCE_OF_EDGE"

    middling = quant.verdict.invoke({"dsr": 0.70, "pbo": 0.30, "wf_positive_share": 0.5})
    assert middling["level"] == "INCONCLUSIVE"


def test_verdict_measures_anything_it_was_not_given():
    """Demo mode calls this with no arguments, so it must not invent the inputs."""
    returns_id = load("returns_noise")
    result = quant.verdict.invoke({"returns_id": returns_id})
    assert result["level"] == "LIKELY_OVERFIT"
    assert set(result["measured_here"]) == {"deflated Sharpe", "overfitting probability"}
    assert result["dsr"] is not None and result["pbo"] is not None


def test_verdict_says_what_it_could_not_measure():
    result = quant.verdict.invoke({"dsr": 0.9, "pbo": 0.1})
    assert any("not measured" in reason for reason in result["reasons"])


def test_odd_or_tiny_block_counts_are_refused():
    returns_id = load("returns_noise")
    assert "error" in quant.pbo_cscv.invoke({"returns_id": returns_id, "blocks": 11})
    assert "error" in quant.pbo_cscv.invoke({"returns_id": returns_id, "blocks": 2})


def test_a_single_variant_cannot_be_ranked():
    single = store(build_matrix(1, cols=1))
    assert "error" in quant.pbo_cscv.invoke({"returns_id": single})

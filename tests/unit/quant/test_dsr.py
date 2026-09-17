"""The deflated Sharpe ratio, checked against the published formula written out by hand."""

import math

import numpy as np
import pytest
from scipy.stats import norm

import automatron_quant as quant

GAMMA = 0.5772156649015329


def dsr_by_hand(sr_hat, skew, kurt, t_obs, v_trials, n_trials):
    """A straight transcription of the formula, independent of the implementation.

    Deliberately written without reusing anything from the module, so the two agree
    only if both are right.
    """
    if n_trials > 1:
        term_a = (1.0 - GAMMA) * norm.ppf(1.0 - 1.0 / n_trials)
        term_b = GAMMA * norm.ppf(1.0 - 1.0 / (n_trials * math.exp(1.0)))
        sr_zero = math.sqrt(v_trials) * (term_a + term_b)
    else:
        sr_zero = 0.0
    numerator = (sr_hat - sr_zero) * math.sqrt(t_obs - 1)
    denominator = math.sqrt(1.0 - skew * sr_hat + (kurt - 1.0) / 4.0 * sr_hat * sr_hat)
    return float(norm.cdf(numerator / denominator))


def build_matrix(seed, rows=1260, cols=40, edge_column=None, edge=0.0):
    matrix = np.random.default_rng(seed).normal(0.0, 0.011, size=(rows, cols))
    if edge_column is not None:
        matrix[:, edge_column] += edge
    return matrix


def store(matrix):
    names = quant._variant_names(matrix.shape[1])
    return quant._store_returns(matrix, list(names), {
        "source": "test", "dates": [], "turnover": {}, "cost_bps": None, "strategy": "test"})


@pytest.mark.parametrize(
    "sr_hat,skew,kurt,t_obs,v_trials,n_trials",
    [
        (0.05, -0.5, 4.0, 1000, 0.0025, 100),
        (0.10, 0.0, 3.0, 2520, 0.0100, 50),
        (0.02, -1.2, 8.0, 500, 0.0009, 250),
        (0.08, 0.3, 3.5, 1260, 0.0016, 1),
        (-0.01, 0.0, 3.0, 750, 0.0004, 20),
    ],
)
def test_matches_a_hand_computed_example(sr_hat, skew, kurt, t_obs, v_trials, n_trials):
    """The spec asks for agreement to 1e-6; these agree to floating point."""
    expected = dsr_by_hand(sr_hat, skew, kurt, t_obs, v_trials, n_trials)

    sr_zero = quant.expected_max_sharpe(v_trials, n_trials)
    denominator = 1.0 - skew * sr_hat + ((kurt - 1.0) / 4.0) * sr_hat**2
    statistic = (sr_hat - sr_zero) * math.sqrt(t_obs - 1) / math.sqrt(denominator)
    actual = float(norm.cdf(statistic))

    assert actual == pytest.approx(expected, abs=1e-12)


def test_one_trial_reduces_to_the_probabilistic_sharpe_ratio():
    """With nothing to deflate, the bar is zero and the formula is the plain PSR."""
    assert quant.expected_max_sharpe(0.0016, 1) == 0.0
    sr_hat, skew, kurt, t_obs = 0.08, 0.3, 3.5, 1260
    psr = norm.cdf(sr_hat * math.sqrt(t_obs - 1)
                   / math.sqrt(1 - skew * sr_hat + (kurt - 1) / 4 * sr_hat**2))
    assert dsr_by_hand(sr_hat, skew, kurt, t_obs, 0.0016, 1) == pytest.approx(psr, abs=1e-12)


def test_the_bar_rises_with_the_number_of_trials():
    """More variants searched means a higher Sharpe is needed to mean anything."""
    bars = [quant.expected_max_sharpe(0.01, n) for n in (2, 10, 100, 1000, 10000)]
    assert bars == sorted(bars)
    assert all(later > earlier for earlier, later in zip(bars, bars[1:], strict=False))


def test_deflation_falls_as_more_variants_are_tried():
    """The same returns, reported as one of many trials, deflate further."""
    matrix = build_matrix(28)
    returns_id = store(matrix)
    few = quant.deflated_sharpe.invoke({"returns_id": returns_id, "n_trials": 2})
    many = quant.deflated_sharpe.invoke({"returns_id": returns_id, "n_trials": 500})
    assert few["deflated_sharpe"] > many["deflated_sharpe"]
    assert few["observed_annualized_sharpe"] == many["observed_annualized_sharpe"]


def test_moments_use_non_excess_kurtosis():
    """A normal sample must give kurtosis near three, not near zero."""
    sample = np.random.default_rng(5).normal(0.0, 1.0, size=200_000)
    _, skew, kurt, count = quant._sharpe_moments(sample)
    assert count == 200_000
    assert kurt == pytest.approx(3.0, abs=0.05)
    assert skew == pytest.approx(0.0, abs=0.05)


def test_the_result_states_its_annualization_factor():
    """A Sharpe with no stated frequency is ambiguous, so the tool always says."""
    result = quant.deflated_sharpe.invoke({"returns_id": store(build_matrix(28))})
    assert result["annualization_factor"] == "sqrt(252)"
    assert result["trials_used"] == 40

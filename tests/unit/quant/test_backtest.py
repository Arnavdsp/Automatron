"""The grid: no look-ahead, costs that bite, and metrics that state their frequency."""

import numpy as np
import pytest

import automatron_quant as quant


@pytest.fixture(scope="module", autouse=True)
def samples():
    quant.ensure_samples()


@pytest.fixture(scope="module")
def closes():
    return quant._read_sample_prices()["SPY"].to_numpy(dtype=float)


def run_variant(series, strategy, params, cost_bps=5.0):
    bar_returns = np.concatenate([[0.0], np.diff(series) / series[:-1]])
    signal = quant.STRATEGIES[strategy]["signal"]
    return quant._variant_returns(series, bar_returns, signal, params, cost_bps / 10000.0)[0]


@pytest.mark.parametrize(
    "strategy,params",
    [("sma_crossover", (10, 50)), ("momentum", (20, 0.0)), ("mean_reversion_zscore", (20, 1.0))],
)
def test_a_future_spike_does_not_leak_backwards(closes, strategy, params):
    """Plant a spike on the last bar; every earlier return must be untouched.

    This is the test that catches a signal peeking forward, which is the single
    easiest way to produce a backtest that cannot be earned.
    """
    spiked = closes.copy()
    spiked[-1] *= 3.0
    before = run_variant(closes, strategy, params)
    after = run_variant(spiked, strategy, params)
    assert np.array_equal(before[:-1], after[:-1])


def test_the_signal_is_shifted_by_exactly_one_bar():
    """A position may only be held on the bar after the signal that justified it."""
    close = np.array([1.0, 1.0, 1.0, 5.0, 5.0, 5.0, 5.0, 5.0], dtype=float)
    bar_returns = np.concatenate([[0.0], np.diff(close) / close[:-1]])

    def always_long(series, *_):
        return np.ones_like(series)

    net, turnover = quant._variant_returns(close, bar_returns, always_long, (), 0.0)
    # The first bar cannot be traded: there is no prior signal to act on.
    assert net[0] == 0.0
    assert turnover == 1.0


def test_costs_reduce_returns_and_scale_with_turnover(closes):
    free = run_variant(closes, "sma_crossover", (5, 40), cost_bps=0.0)
    cheap = run_variant(closes, "sma_crossover", (5, 40), cost_bps=5.0)
    dear = run_variant(closes, "sma_crossover", (5, 40), cost_bps=50.0)
    assert free.sum() > cheap.sum() > dear.sum()


def test_the_grid_covers_every_combination():
    result = quant.run_backtest_grid.invoke(
        {"strategy": "sma_crossover", "ticker": "SPY",
         "param_grid": {"fast": [5, 10], "slow": [40, 80, 120]}})
    assert result["variants_tested"] == 6
    assert result["trials_tried"] == 6
    assert result["annualization_factor"] == "sqrt(252)"


def test_an_unknown_strategy_is_refused_by_name():
    result = quant.run_backtest_grid.invoke({"strategy": "martingale_doubling"})
    assert "error" in result and "martingale_doubling" in result["error"]


def test_a_grid_missing_a_parameter_is_refused():
    result = quant.run_backtest_grid.invoke(
        {"strategy": "sma_crossover", "param_grid": {"fast": [5, 10]}})
    assert "error" in result


def test_metrics_report_drawdown_and_state_the_factor():
    quant.run_backtest_grid.invoke({"strategy": "sma_crossover", "ticker": "SPY"})
    metrics = quant.performance_metrics.invoke({})
    assert metrics["annualization_factor"] == "sqrt(252)"
    assert metrics["max_drawdown_pct"] <= 0.0
    assert 0.0 <= metrics["hit_rate_pct"] <= 100.0
    assert metrics["observations"] > 1000


def test_walk_forward_chooses_on_the_past_only():
    result = quant.walk_forward.invoke(
        {"strategy": "sma_crossover", "ticker": "SPY", "folds": 4,
         "param_grid": {"fast": [5, 10, 20], "slow": [40, 90]}})
    assert result["folds_completed"] == 4
    assert 0.0 <= result["positive_share"] <= 1.0
    # Each fold must train on strictly more history than the one before it.
    sizes = [fold["train_bars"] for fold in result["folds"]]
    assert sizes == sorted(sizes) and len(set(sizes)) == len(sizes)


def test_loading_a_matrix_reports_its_shape():
    result = quant.load_returns_matrix.invoke({"sample_name": "returns_noise"})
    assert result["variants"] == 40
    assert result["observations"] == 1260
    assert result["warning"] == ""


def test_prices_default_to_the_bundled_sample_without_network():
    result = quant.fetch_prices.invoke({"tickers": ["SPY", "AAPL"]})
    assert result["source"] == "bundled_sample"
    assert result["synthetic"] is True
    assert result["tickers"] == ["SPY", "AAPL"]
    assert result["bars"] == 2016


def test_unknown_tickers_are_named_not_silently_dropped():
    result = quant.fetch_prices.invoke({"tickers": ["SPY", "NOTATICKER"]})
    assert result["missing_tickers"] == ["NOTATICKER"]

"""The trade gate: sizing, limits, lists, and the level each ticket lands on."""

import pytest

import automatron_quant as quant


@pytest.fixture(scope="module", autouse=True)
def samples():
    quant.ensure_samples()


def test_the_three_sample_tickets_take_three_different_paths():
    """Each sample exists to demonstrate a distinct reason a human is needed."""
    small = quant.gate_decision.invoke({"sample_name": "ticket_small_ok"})
    assert small["level"] == "WITHIN_LIMITS_FAST_TRACK"
    assert small["triggers"] == []

    large = quant.gate_decision.invoke({"sample_name": "ticket_large_highrisk"})
    assert large["level"] == "HUMAN_APPROVAL_REQUIRED"
    assert any("approval threshold" in t for t in large["triggers"])
    assert any("high-risk" in t for t in large["triggers"])

    listed = quant.gate_decision.invoke({"sample_name": "ticket_restricted"})
    assert listed["level"] == "HUMAN_APPROVAL_REQUIRED"
    assert any("restricted list" in t for t in listed["triggers"])


def test_the_sample_book_is_inside_its_own_limits():
    """A book that already breached would make every ticket look like a breach."""
    rows = quant._read_csv_rows("book.csv")
    total = sum(float(r["market_value_usd"]) for r in rows)
    limits = quant.load_trade_limits()["concentration"]

    largest = max(float(r["market_value_usd"]) for r in rows) / total * 100
    assert largest < limits["warn_single_name_pct"]

    sectors: dict[str, float] = {}
    for row in rows:
        sectors[row["sector"]] = sectors.get(row["sector"], 0.0) + float(row["market_value_usd"])
    assert max(sectors.values()) / total * 100 < limits["max_sector_pct"]


def test_notional_uses_a_stated_reference_rate():
    result = quant.compute_notional.invoke({"sample_name": "ticket_small_ok"})
    assert result["notional_usd"] == pytest.approx(120 * 402.50)
    assert result["fx_rate_to_usd"] == 1.0
    assert result["fx_rates_as_of"] == "2026-01-02"
    assert "not a market quote" in result["rate_note"]


def test_a_non_usd_ticket_is_converted_and_says_so():
    ticket = {"ticket_id": "T-1", "instrument": "MSFT", "asset_class": "equity", "side": "BUY",
              "quantity": 100, "limit_price": 100.0, "currency": "EUR", "client_id": "C-1",
              "client_segment": "PROFESSIONAL", "strategy_id": "momentum_us_lc",
              "trader": "t"}
    result = quant.compute_notional.invoke({"ticket": ticket})
    assert result["local_notional"] == 10_000.0
    assert result["notional_usd"] == pytest.approx(10_000.0 * 1.0850)
    assert result["currency"] == "EUR"


def test_an_unknown_currency_is_refused_rather_than_assumed():
    ticket = {"ticket_id": "T-2", "instrument": "MSFT", "asset_class": "equity", "side": "BUY",
              "quantity": 1, "limit_price": 1.0, "currency": "XYZ", "client_id": "C-1",
              "client_segment": "RETAIL", "strategy_id": "discretionary", "trader": "t"}
    assert "error" in quant.compute_notional.invoke({"ticket": ticket})
    problems = quant.validate_ticket.invoke({"ticket": ticket})["problems"]
    assert any("XYZ" in p for p in problems)


def test_missing_fields_are_named_not_guessed():
    result = quant.validate_ticket.invoke({"ticket": {"ticket_id": "T-3", "instrument": "MSFT"}})
    assert result["valid"] is False
    named = " ".join(result["problems"])
    for field in ("quantity", "limit_price", "currency", "client_segment", "trader"):
        assert field in named


@pytest.mark.parametrize("quantity,price", [(0, 10.0), (-5, 10.0), (10, 0.0), (10, -1.0)])
def test_non_positive_size_or_price_is_rejected(quantity, price):
    ticket = {"ticket_id": "T-4", "instrument": "MSFT", "asset_class": "equity", "side": "BUY",
              "quantity": quantity, "limit_price": price, "currency": "USD", "client_id": "C-1",
              "client_segment": "RETAIL", "strategy_id": "discretionary", "trader": "t"}
    assert quant.validate_ticket.invoke({"ticket": ticket})["valid"] is False


def test_every_breach_reports_the_threshold_it_compared_against():
    """A brief has to show the arithmetic, not assert that a limit was broken."""
    result = quant.check_limits.invoke({"sample_name": "ticket_large_highrisk"})
    assert result["breach_count"] > 0
    for breach in result["breaches"]:
        assert "rule" in breach
        assert ("limit_usd" in breach) or ("limit_pct" in breach)


def test_value_at_risk_comes_from_the_history_not_a_normal_assumption():
    result = quant.pre_trade_var.invoke({"sample_name": "ticket_large_highrisk"})
    assert result["confidence"] == 0.99
    assert result["horizon_days"] == 1
    assert result["var_usd"] > 0
    assert result["observations_used"] >= 120
    assert "historical simulation" in result["method"]


def test_a_client_scoped_list_entry_only_applies_to_that_client():
    """PFE is restricted for C-2001 alone; anyone else must come back clean."""
    theirs = quant.restricted_list_check.invoke({"instrument": "PFE", "client_id": "C-2001"})
    assert theirs["restricted"] is True

    others = quant.restricted_list_check.invoke({"instrument": "PFE", "client_id": "C-1044"})
    assert others["restricted"] is False
    assert others["hits"] == []


def test_a_watch_entry_is_reported_without_forcing_approval():
    result = quant.restricted_list_check.invoke({"instrument": "XOM", "client_id": "C-1044"})
    assert result["restricted"] is False
    assert result["watch_only"] is True


def test_the_gate_never_claims_an_order_was_placed():
    for sample in ("ticket_small_ok", "ticket_large_highrisk", "ticket_restricted"):
        note = quant.gate_decision.invoke({"sample_name": sample})["note"]
        assert "Nothing in this system places" in note

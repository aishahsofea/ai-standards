import pytest

from pipeline.cost import BudgetExceeded, CostLedger


def test_empty_ledger_totals_zero(tmp_path):
    assert CostLedger(tmp_path / "cost.csv").total() == 0.0


def test_record_writes_header_once_and_rows(tmp_path):
    path = tmp_path / "cost.csv"
    ledger = CostLedger(path)
    ledger.record("analyze", "opus", 1.5)
    ledger.record("plan", "sonnet", 0.25)
    assert path.read_text().splitlines() == [
        "stage,model,cost_usd",
        "analyze,opus,1.5",
        "plan,sonnet,0.25",
    ]


def test_total_sums_costs(tmp_path):
    ledger = CostLedger(tmp_path / "cost.csv")
    ledger.record("a", "m", 1.5)
    ledger.record("b", "m", 2.25)
    assert ledger.total() == 3.75


def test_check_passes_at_cap_and_raises_past_it(tmp_path):
    ledger = CostLedger(tmp_path / "cost.csv", budget_usd=2.0)
    ledger.record("a", "m", 2.0)
    ledger.check()
    ledger.record("b", "m", 0.01)
    with pytest.raises(BudgetExceeded, match="2.01"):
        ledger.check()


def test_resumed_run_counts_earlier_spend(tmp_path):
    path = tmp_path / "cost.csv"
    CostLedger(path).record("a", "m", 14.0)
    resumed = CostLedger(path, budget_usd=15.0)
    assert resumed.total() == 14.0
    resumed.record("b", "m", 2.0)
    with pytest.raises(BudgetExceeded):
        resumed.check()
    assert path.read_text().count("stage,model,cost_usd") == 1


def test_default_budget_is_fifteen(tmp_path):
    assert CostLedger(tmp_path / "cost.csv").budget_usd == 15.0

import pytest

from pipeline.cost import BudgetExceeded, CostLedger, prior_total, render_table


def test_empty_ledger_totals_zero():
    assert CostLedger().total() == 0.0


def test_total_sums_costs():
    ledger = CostLedger()
    ledger.record("a", "m", 1.5)
    ledger.record("b", "m", 2.25)
    assert ledger.total() == 3.75


def test_check_passes_at_cap_and_raises_past_it():
    ledger = CostLedger(budget_usd=2.0)
    ledger.record("a", "m", 2.0)
    ledger.check()
    ledger.record("b", "m", 0.01)
    with pytest.raises(BudgetExceeded, match="2.01"):
        ledger.check()


def test_prior_spend_counts_toward_budget():
    ledger = CostLedger(budget_usd=15.0, prior_usd=14.0)
    assert ledger.total() == 14.0
    ledger.record("b", "m", 2.0)
    with pytest.raises(BudgetExceeded):
        ledger.check()


def test_default_budget_is_fifteen():
    assert CostLedger().budget_usd == 15.0


def test_table_lists_stages_total_and_budget():
    ledger = CostLedger(budget_usd=15.0)
    ledger.record("analyze", "opus", 1.5)
    ledger.record("plan", "sonnet", 0.25)
    assert render_table(ledger).splitlines() == [
        "| stage | model | cost_usd |",
        "|---|---|---|",
        "| analyze | opus | 1.5000 |",
        "| plan | sonnet | 0.2500 |",
        "",
        "Total: $1.7500 of $15.00 budget",
    ]


def test_table_shows_earlier_runs_as_one_row():
    ledger = CostLedger(prior_usd=1.0)
    ledger.record("test", "sonnet", 0.5)
    assert "| earlier runs | - | 1.0000 |" in render_table(ledger)
    assert "Total: $1.5000" in render_table(ledger)


def test_prior_total_reads_the_rendered_table():
    ledger = CostLedger(prior_usd=1.0)
    ledger.record("test", "sonnet", 0.5)
    assert prior_total(render_table(ledger)) == 1.5


@pytest.mark.parametrize("comment", [None, "", "no total here"])
def test_prior_total_defaults_to_zero(comment):
    assert prior_total(comment) == 0.0

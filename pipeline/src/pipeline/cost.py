import re

DEFAULT_BUDGET_USD = 15.0
TOTAL_LINE = re.compile(r"^Total: \$(\d+(?:\.\d+)?)", re.MULTILINE)


class BudgetExceeded(Exception):
    pass


class CostLedger:
    def __init__(self, budget_usd: float = DEFAULT_BUDGET_USD, prior_usd: float = 0.0) -> None:
        self.budget_usd = budget_usd
        self.prior_usd = prior_usd
        self.records: list[tuple[str, str, float]] = []

    def record(self, stage: str, model: str, cost_usd: float) -> None:
        self.records.append((stage, model, cost_usd))

    def total(self) -> float:
        return self.prior_usd + sum(cost for *_, cost in self.records)

    def check(self) -> None:
        total = self.total()
        if total > self.budget_usd:
            raise BudgetExceeded(f"spent ${total:.2f}, over the ${self.budget_usd:.2f} budget")


def render_table(ledger: CostLedger) -> str:
    rows = [("earlier runs", "-", ledger.prior_usd)] if ledger.prior_usd else []
    lines = ["| stage | model | cost_usd |", "|---|---|---|"]
    lines += [f"| {stage} | {model} | {cost:.4f} |" for stage, model, cost in [*rows, *ledger.records]]
    lines += ["", f"Total: ${ledger.total():.4f} of ${ledger.budget_usd:.2f} budget"]
    return "\n".join(lines)


def prior_total(comment: str | None) -> float:
    match = TOTAL_LINE.search(comment or "")
    return float(match[1]) if match else 0.0

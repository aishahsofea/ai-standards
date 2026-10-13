import csv
from pathlib import Path

DEFAULT_BUDGET_USD = 15.0
HEADER = ["stage", "model", "cost_usd"]


class BudgetExceeded(Exception):
    pass


class CostLedger:
    def __init__(self, path: Path, budget_usd: float = DEFAULT_BUDGET_USD) -> None:
        self.path = path
        self.budget_usd = budget_usd

    def record(self, stage: str, model: str, cost_usd: float) -> None:
        is_new = not self.path.exists()
        with self.path.open("a", newline="") as file:
            writer = csv.writer(file)
            if is_new:
                writer.writerow(HEADER)
            writer.writerow([stage, model, cost_usd])

    def total(self) -> float:
        if not self.path.exists():
            return 0.0
        with self.path.open(newline="") as file:
            return sum(float(row["cost_usd"]) for row in csv.DictReader(file))

    def check(self) -> None:
        total = self.total()
        if total > self.budget_usd:
            raise BudgetExceeded(f"spent ${total:.2f}, over the ${self.budget_usd:.2f} budget")

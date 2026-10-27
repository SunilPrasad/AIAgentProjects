"""The spending cap for a book. Every AI call checks it before running and adds to it after."""

from __future__ import annotations

from bookguild import storage
from bookguild.reliability import BudgetExceeded
from bookguild.storage import Book


class Budget:
    def __init__(self, limit_usd: float, spent_usd: float = 0.0, book: Book | None = None):
        self._limit_usd = limit_usd
        self.spent_usd = spent_usd
        self.book = book  # when set, the limit comes from the book and spending is saved to state.json

    @classmethod
    def for_book(cls, book: Book) -> Budget:
        return cls(limit_usd=book.budget_usd, spent_usd=book.spent_usd, book=book)

    @property
    def limit_usd(self) -> float:
        # Read from the book each time, so changing the budget in the Book Profile applies at once.
        return self.book.budget_usd if self.book is not None else self._limit_usd

    def check(self) -> None:
        """Raise BudgetExceeded if no more money may be spent."""
        if self.spent_usd >= self.limit_usd:
            raise BudgetExceeded(self.spent_usd, self.limit_usd)

    def add(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd
        if self.book is not None:
            self.book.spent_usd = self.spent_usd
            storage.save_book(self.book)


def format_usd(amount: float) -> str:
    """$1.23 normally; more decimals for tiny amounts so a real cost never shows as $0.00."""
    if 0 < amount < 0.01:
        return f"${amount:.5f}"
    return f"${amount:.2f}"

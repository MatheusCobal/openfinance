from typing import List, Optional

from sqlmodel import Session, select

from app.models import Category, CategoryRule

FALLBACK_NAME = "Outros"
FALLBACK_COLOR = "#64748b"


class CategoryResolver:
    """Resolves Pluggy categories to user-defined categories.

    Loads all rules and categories into memory once per request so
    resolving N transactions costs N dict lookups instead of N queries.
    """

    def __init__(self, session: Session) -> None:
        self._categories_by_id = {
            c.id: c for c in session.exec(select(Category)).all()
        }
        self._rule_to_category_id = {
            rule.pluggy_category: rule.category_id
            for rule in session.exec(select(CategoryRule)).all()
        }
        self._fallback = next(
            (c for c in self._categories_by_id.values() if c.name == FALLBACK_NAME),
            None,
        )

    def resolve(self, pluggy_category: Optional[str]) -> Category:
        if pluggy_category is not None:
            category_id = self._rule_to_category_id.get(pluggy_category)
            if category_id is not None and category_id in self._categories_by_id:
                return self._categories_by_id[category_id]
        if self._fallback is not None:
            return self._fallback
        # No fallback configured yet (categories not seeded). Return a synthetic
        # one so the caller doesn't need to handle None.
        return Category(id=0, name=FALLBACK_NAME, color=FALLBACK_COLOR, sort_order=999)

    def all_categories(self) -> List[Category]:
        return sorted(
            self._categories_by_id.values(), key=lambda c: (c.sort_order, c.name)
        )

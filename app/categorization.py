import unicodedata
from typing import List, Optional

from sqlmodel import Session, select

from app.models import Category, CategoryRule, DescriptionCategoryRule

FALLBACK_NAME = "Outros"
FALLBACK_COLOR = "#64748b"


def normalize_description(text: Optional[str]) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_accents.casefold().split())


class CategoryResolver:
    """Resolves Pluggy categories to user-defined categories.

    Loads all rules and categories into memory once per request so
    resolving N transactions costs N dict lookups instead of N queries.
    """

    def __init__(self, session: Session) -> None:
        self._categories_by_id = {c.id: c for c in session.exec(select(Category)).all()}
        self._rule_to_category_id = {
            rule.pluggy_category: rule.category_id
            for rule in session.exec(select(CategoryRule)).all()
        }
        self._description_rules = sorted(
            [
                (rule.pattern_normalized, rule.category_id)
                for rule in session.exec(select(DescriptionCategoryRule)).all()
                if rule.pattern_normalized
            ],
            key=lambda rule: len(rule[0]),
            reverse=True,
        )
        self._fallback = next(
            (c for c in self._categories_by_id.values() if c.name == FALLBACK_NAME),
            None,
        )

    def resolve(
        self,
        pluggy_category: Optional[str],
        description: Optional[str] = None,
    ) -> Category:
        normalized_description = normalize_description(description)
        if normalized_description:
            for pattern, category_id in self._description_rules:
                if pattern in normalized_description and category_id in self._categories_by_id:
                    return self._categories_by_id[category_id]
        if pluggy_category is not None:
            category_id = self._rule_to_category_id.get(pluggy_category)
            if category_id is not None and category_id in self._categories_by_id:
                return self._categories_by_id[category_id]
        if self._fallback is not None:
            return self._fallback
        # No fallback configured yet (categories not seeded). Return a synthetic
        # one so the caller doesn't need to handle None.
        return Category(id=0, name=FALLBACK_NAME, color=FALLBACK_COLOR, sort_order=999)

    def display_category(self, category: Category) -> Category:
        """If this is a sub-category (has parent_id), return the parent.
        Otherwise return the category itself. Used to collapse sub-categories
        for budget tracking and dashboard grouping."""
        if category.parent_id and category.parent_id in self._categories_by_id:
            return self._categories_by_id[category.parent_id]
        return category

    def all_categories(self) -> List[Category]:
        return sorted(self._categories_by_id.values(), key=lambda c: (c.sort_order, c.name))

    def all_top_level_categories(self) -> List[Category]:
        """Returns only root categories (no parent). Use for budgets and top-level charts."""
        return sorted(
            [c for c in self._categories_by_id.values() if not c.parent_id],
            key=lambda c: (c.sort_order, c.name),
        )

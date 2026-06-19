"""Per-user query scoping (Fase 6).

A single helper that conditionally applies a ``WHERE user_id = ?`` filter.

The contract across the service layer is that ``user_id`` is ``Optional[int]``:

* ``None`` — auth-disabled / local-open mode (a single shared dataset). No
  isolation filter is applied, which also keeps the existing test suite, whose
  fixtures don't set ``user_id``, working unchanged.
* a concrete ``int`` — restrict the query to rows owned by that user. This is
  what every authenticated request passes (see ``current_scope_user_id``).
"""

from typing import Optional


def scope_query(query, column, user_id: Optional[int]):
    """Restrict ``query`` to ``column == user_id`` only when ``user_id`` is set."""
    if user_id is None:
        return query
    return query.where(column == user_id)

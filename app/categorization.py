import unicodedata
from typing import Optional

# 10D-A: legacy financial category resolution was removed. This module keeps
# only description normalization helpers that are still used by non-category
# flows such as deduplication, invoice-payment detection and exclusion rules.


def normalize_description(text: Optional[str]) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(without_accents.casefold().split())

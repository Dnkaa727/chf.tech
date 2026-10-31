"""Локальный объяснимый поиск без embeddings и без платных API."""

from __future__ import annotations

import re


def normalize(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").strip().split())


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[\w]+", normalize(text), flags=re.UNICODE))


def term_in_query(term: str, query: str) -> bool:
    """Ищем словосочетание без ложных совпадений SQL внутри SQLAlchemy."""
    t, q = normalize(term), normalize(query)
    return bool(t and re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", q))


def related_token(a: str, b: str) -> bool:
    """Упрощённое сближение русских окончаний: индекс/индексы, запрос/запросов."""
    if a == b:
        return True
    if len(a) >= 6 and len(b) >= 6 and any("а" <= ch <= "я" for ch in a + b):
        return a[:5] == b[:5]
    return False

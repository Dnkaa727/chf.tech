"""Локальный объяснимый поиск без embeddings и без платных API."""
from __future__ import annotations

import re

from .kb import public_metadata


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
    if len(a) >= 6 and len(b) >= 6 and any("а" <= ch <= "я" for ch in a+b):
        return a[:5] == b[:5]
    return False


def retrieve(cards: list[dict], query: str = "", competency: str | None = None, limit: int = 3) -> list[dict]:
    """Возвращает подходящие карточки, объясняемые оценки релевантности и метаданные.

    competency - необязательный точный фильтр по имени / синониму компетенции.
    query - тема / формулировка задачи; без темы выдаём приоритетные карточки навыка.
    """
    if not 1 <= limit <= 20:
        raise ValueError("limit должен быть от 1 до 20")
    q = normalize(query)
    f = normalize(competency or "")
    if not q and not f:
        return []
    found = []
    for card in cards:
        names = [card["competency"], *card["aliases"]]
        if f and not any(normalize(name) == f for name in names):
            continue
        score = 0.0
        reasons = []
        if f:
            score += 10
            reasons.append("фильтр по компетенции")
        if q:
            if normalize(card["id"]) == q:
                score += 50
                reasons.append("точный ID")
            for name in set(names):
                if term_in_query(name, q):
                    score += 6 if normalize(name) == q else 3
                    reasons.append(f"название/синоним: {name}")
                    break
            for tag in card["retrieval_tags"]:
                if term_in_query(tag, q):
                    score += 5
                    reasons.append(f"тег: {tag}")
            q_toks = tokens(q)
            for word in tokens(card["topic"]):
                if len(word) > 3 and any(related_token(word, t) for t in q_toks):
                    score += 2
                    reasons.append(f"тема: {word}")
        if score <= 0:
            continue
        if card["priority_for_demo"] == "core":
            score += 0.25
        found.append({
            **public_metadata(card), "score":round(score,2),
            "matches": sorted(set(reasons)),
            "source_urls": [s["url"] for s in card["source_vacancies"]],
        })
    return sorted(found,key=lambda x:(-x["score"],x["id"]))[:limit]

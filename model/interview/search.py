"""Explainable card selection used by the unified interview model."""

from __future__ import annotations

import re


def normalize(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").strip().split())


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[\w]+", normalize(text), flags=re.UNICODE))


def term_in_query(term: str, query: str) -> bool:
    normalized_term = normalize(term)
    normalized_query = normalize(query)
    return bool(
        normalized_term
        and re.search(
            r"(?<!\w)" + re.escape(normalized_term) + r"(?!\w)",
            normalized_query,
        )
    )


def related_token(first: str, second: str) -> bool:
    if first == second:
        return True
    return (
        len(first) >= 6
        and len(second) >= 6
        and any("а" <= char <= "я" for char in first + second)
        and first[:5] == second[:5]
    )


def public_metadata(card: dict) -> dict:
    return {
        "id": card["id"],
        "competency": card["competency"],
        "topic": card["topic"],
        "target_level": card["target_level"],
        "demo_priority": card["priority_for_demo"],
        "review_status": card["review_status"],
    }


def retrieve(
    cards: list[dict],
    query: str = "",
    competency: str | None = None,
    limit: int = 3,
) -> list[dict]:
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")

    normalized_query = normalize(query)
    normalized_competency = normalize(competency or "")
    if not normalized_query and not normalized_competency:
        return []

    found = []
    for card in cards:
        names = [card["competency"], *card["aliases"]]
        if normalized_competency and not any(
            normalize(name) == normalized_competency for name in names
        ):
            continue

        score = 10.0 if normalized_competency else 0.0
        reasons = ["competency filter"] if normalized_competency else []
        if normalized_query:
            if normalize(card["id"]) == normalized_query:
                score += 50
                reasons.append("exact ID")
            for name in set(names):
                if term_in_query(name, normalized_query):
                    score += 6 if normalize(name) == normalized_query else 3
                    reasons.append(f"name/alias: {name}")
                    break
            for tag in card["retrieval_tags"]:
                if term_in_query(tag, normalized_query):
                    score += 5
                    reasons.append(f"tag: {tag}")
            query_tokens = tokens(normalized_query)
            for word in tokens(card["topic"]):
                if len(word) > 3 and any(
                    related_token(word, token) for token in query_tokens
                ):
                    score += 2
                    reasons.append(f"topic: {word}")

        if score <= 0:
            continue
        if card["priority_for_demo"] == "core":
            score += 0.25
        found.append(
            {
                **public_metadata(card),
                "score": round(score, 2),
                "matches": sorted(set(reasons)),
                "source_urls": [source["url"] for source in card["source_vacancies"]],
            }
        )

    return sorted(found, key=lambda item: (-item["score"], item["id"]))[:limit]

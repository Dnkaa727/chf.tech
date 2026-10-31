"""Legacy v1/v2 loader. Current v3 catalog and rubrics use v3.registry."""
from __future__ import annotations

import json
from pathlib import Path

KB_PATH = Path(__file__).resolve().parents[1] / "data" / "legacy" / "knowledge_base_v1.json"
REQUIRED_CARD_FIELDS = {
    "id", "competency", "topic", "question", "criteria", "followup_questions",
    "source_vacancies", "review_status", "retrieval_tags", "aliases"
}


def load_kb(path: Path = KB_PATH) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0" or not isinstance(payload.get("cards"), list):
        raise ValueError("Неизвестный формат базы знаний")
    cards = payload["cards"]
    seen = set()
    for card in cards:
        missing = REQUIRED_CARD_FIELDS.difference(card)
        if missing:
            raise ValueError(f"В карточке {card.get('id', '?')} нет полей: {sorted(missing)}")
        if card["id"] in seen:
            raise ValueError(f"Повторный ID карточки: {card['id']}")
        seen.add(card["id"])
        if not card["criteria"] or not card["source_vacancies"]:
            raise ValueError(f"Карточка {card['id']} не содержит критериев или источников")
    return cards


def get_card(cards: list[dict], card_id: str) -> dict | None:
    return next((c for c in cards if c["id"] == card_id), None)


def public_metadata(card: dict) -> dict:
    """Метаданные без рубрики (критерии и эталоны нельзя отдавать кандидату)."""
    return {
        "id": card["id"], "competency": card["competency"],
        "topic": card["topic"], "target_level": card["target_level"],
        "demo_priority": card["priority_for_demo"],
        "review_status": card["review_status"]
    }

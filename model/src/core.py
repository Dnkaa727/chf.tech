"""Чистая логика прототипа: без LLM, БД и платных сервисов."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRITERIA_IDS = ("diagnosis", "plan", "statistics", "index", "verification")


def read_data(filename):
    return json.loads((ROOT / "data" / filename).read_text(encoding="utf-8"))


def retrieve(query, competency=None, top_k=3):
    """Базовый прозрачный keyword retrieval; НЕ векторный поиск."""
    cards = read_data("knowledge_cards.json")
    query_words = {s.casefold() for s in query.split() if len(s) >= 3}
    ranked = []
    for card in cards:
        if competency and card["competency"].casefold() != competency.casefold():
            continue
        score = 0
        content = (" ".join([card["competency"], card["topic"], *card["tags"]])).casefold()
        if query.casefold() in content:
            score += 10
        score += sum(2 for word in query_words if word in content)
        ranked.append((score, card))
    ranked.sort(key=lambda item: (-item[0], item[1]["id"]))
    return [card for score, card in ranked[:top_k] if score > 0]


def verify_quote(answer, quote):
    """Проверяет буквальную цитату, а не смысл. Неточное цитирование отклоняется."""
    return bool(quote and quote.strip() and quote.strip() in answer)


def verify_model_output(result, answer):
    """Обрезает баллы без подтверждающей цитаты. НЕ доказывает семантическую правоту цитаты."""
    result = dict(result)
    raw = result.get("criteria", {})
    clean = {}
    warnings = []
    for cid in CRITERIA_IDS:
        value = raw.get(cid, {})
        claimed = value.get("points", 0)
        if type(claimed) is not int or not 0 <= claimed <= 2:
            raise ValueError(f"Invalid points: {cid}={claimed!r}")
        evidence = value.get("quote", "")
        if claimed > 0 and not verify_quote(answer, evidence):
            warnings.append(f"No verified quote for {cid}; points reset to 0")
            claimed = 0
        clean[cid] = {"points": claimed, "quote": evidence if verify_quote(answer, evidence) else ""}
    result["criteria"] = clean
    result["score"] = sum(x["points"] for x in clean.values())
    result["warnings"] = warnings
    return result


def decide_next(assessment, state, rubric=None):
    """Детерминированная политика: максимум 2 уточнения в теме."""
    rubric = rubric or read_data("rubric_postgresql.json")
    flags = set(assessment.get("red_flags", []))
    if assessment.get("abstained") or "prompt_injection" in flags:
        return {"action": "needs_review", "reason": "Unable to trust automated assessment"}
    if assessment.get("refused"):
        return {"action": "next_topic", "reason": "Candidate declined to answer"}
    if assessment.get("uncertainty") == "high":
        return {"action": "needs_review", "reason": "Low evaluation confidence; do not auto-score"}
    if assessment["score"] >= 7 and flags.intersection({"confidently_incorrect", "technical_contradiction", "keyword_stuffing", "evasion"}):
        return {"action": "needs_review", "reason": "High score conflicts with low-evidence/error flags"}
    turns = int(state.get("followups_asked", 0))
    if assessment["score"] >= 8:
        return {"action": "next_topic", "reason": "Sufficient evidence for this topic"}
    if turns >= 2:
        return {"action": "insufficient_evidence", "reason": "Follow-up limit reached"}
    per_criterion = assessment["criteria"]
    # Приоритет темы с наименьшим доказанным баллом.
    already = set(state.get("asked_targets", []))
    missing = sorted(CRITERIA_IDS, key=lambda c: (c in already, per_criterion[c]["points"], CRITERIA_IDS.index(c)))
    target = missing[0]
    return {"action": "followup", "target": target, "question": rubric["followups"][target], "reason": "Target the weakest evidenced criterion"}


def merge_evidence(current, new):
    """Накопление по критериям: берём максимум, не складываем одну и ту же заслугу дважды."""
    merged = {}
    for cid in CRITERIA_IDS:
        a = current.get(cid, {}).get("points", 0)
        b = new.get(cid, {}).get("points", 0)
        merged[cid] = current.get(cid, {"points": 0, "quote": ""}) if a >= b else new[cid]
    return merged

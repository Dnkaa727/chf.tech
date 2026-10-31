"""Unified 25-card scoring endpoints. LOCAL TRUSTED DEMO ONLY; no auth/persistence."""

from threading import Lock
from weakref import WeakKeyDictionary
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from rag.engine import (
    rubrics,
    validate_data,
    TopicSession,
    segmentation_messages_for,
    public_assessment,
)
from rag.llm import evaluate_live
from rag.registry import get_registry, public_card, CardNotFound, AmbiguousCardSelection
from rag.diagnostics import failure_headers

router = APIRouter(prefix="/api", tags=["Interview"])
SESSIONS: dict[str, TopicSession] = {}
# Locks live outside session state, which must remain serializable/copyable.
# Weak keys release locks when their sessions are removed from the store.
_SESSION_LOCKS = WeakKeyDictionary()
_LOCKS_GUARD = Lock()


class _AnswerValidation(BaseModel):
    @field_validator("candidate_answer", check_fields=False)
    @classmethod
    def nonblank_answer(cls, value):
        if not value.strip():
            raise ValueError("candidate_answer must contain text")
        return value


class EvaluationRequest(_AnswerValidation):
    card_id: str = Field(min_length=1, max_length=100)
    candidate_answer: str = Field(min_length=1, max_length=15000)


class StartRequest(BaseModel):
    card_id: str = Field(min_length=1, max_length=100)


class SessionAnswerRequest(_AnswerValidation):
    session_id: str = Field(min_length=1, max_length=100)
    candidate_answer: str = Field(min_length=1, max_length=15000)


class SelectionRequest(BaseModel):
    card_id: str | None = Field(default=None, min_length=1, max_length=100)
    query: str = Field(default="", max_length=400)
    competency: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def selection_input(self):
        if not (self.card_id or self.query.strip() or (self.competency or "").strip()):
            raise ValueError("Specify card_id, query or competency")
        return self


class PublicCard(BaseModel):
    card_id: str
    competency: str
    topic: str
    question: str
    target_level: str
    demo_priority: str
    review_status: str
    aliases: list[str]
    retrieval_tags: list[str]
    source_urls: list[str]


class CatalogResponse(BaseModel):
    cards: list[PublicCard]
    registry_version: str


class SelectionResponse(BaseModel):
    card: PublicCard
    rubric_version: str
    registry_version: str


def selected_entry(card_id):
    try:
        return get_registry().get(card_id)
    except CardNotFound:
        raise HTTPException(404, "Unknown card_id") from None


@router.get("/cards", response_model=CatalogResponse, tags=["Knowledge catalog"])
def catalog():
    registry = get_registry()
    return {"cards": registry.public_cards(), "registry_version": registry.version}


@router.post(
    "/cards/select", response_model=SelectionResponse, tags=["Knowledge catalog"]
)
def select_card(req: SelectionRequest):
    try:
        entry = get_registry().select(
            card_id=req.card_id, query=req.query, competency=req.competency
        )
    except AmbiguousCardSelection as error:
        raise HTTPException(
            409,
            {
                "code": "ambiguous_card",
                "message": str(error),
                "candidates": error.candidates,
            },
        ) from None
    except CardNotFound:
        raise HTTPException(
            404, {"code": "card_not_found", "message": "No matching card"}
        ) from None
    return {
        "card": public_card(entry.card),
        "rubric_version": entry.rubric_version,
        "registry_version": entry.registry_version,
    }


@router.get("/info")
def info():
    result = validate_data()
    result["note"] = "All draft rubrics; never automatically accept/reject people"
    return result


@router.get("/rubrics")
def available():
    return [
        {
            "card_id": r["card_id"],
            "topic": r["topic"],
            "review_status": r["status"],
            "max_points": 10,
            "criteria_count": 5,
        }
        for r in rubrics().values()
    ]


@router.post("/prepare", tags=["Internal prompts"])
def prepare(req: EvaluationRequest):
    entry = selected_entry(req.card_id)
    return {
        "card_id": req.card_id,
        "pipeline": "two_stage_v1",
        "messages": segmentation_messages_for(
            req.card_id, req.candidate_answer, rubric=entry.rubric
        ),
        "note": "INTERNAL ONLY - first-stage messages contain hidden rubric routing data",
    }


@router.post("/evaluate")
def evaluate(req: EvaluationRequest):
    entry = selected_entry(req.card_id)
    try:
        return public_assessment(
            evaluate_live(req.card_id, req.candidate_answer, rubric=entry.rubric)
        )
    except (RuntimeError, ValueError, TypeError) as error:
        headers = failure_headers(
            error,
            card_id=req.card_id,
            criterion_ids=[c["id"] for c in entry.rubric["criteria"]],
        )
        raise HTTPException(
            502,
            "LLM evaluation failed. Retry or request human review.",
            headers=headers,
        ) from None


@router.post("/session/start")
def start(req: StartRequest):
    try:
        s = TopicSession(req.card_id)
    except CardNotFound:
        raise HTTPException(404, "Unknown card_id") from None
    SESSIONS[s.session_id] = s
    return {
        "session_id": s.session_id,
        "card_id": s.card_id,
        "question": s.pending_question,
        "status": s.status,
        "max_followups": s.max_followups,
    }


@router.post("/session/answer")
def session_answer(req: SessionAnswerRequest):
    s = SESSIONS.get(req.session_id)
    if s is None:
        raise HTTPException(404, "Unknown/expired session")
    with _LOCKS_GUARD:
        lock = _SESSION_LOCKS.setdefault(s, Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(
            409, "An answer is already being evaluated for this session"
        )
    try:
        if s.status != "in_progress":
            raise HTTPException(409, "Session already finished")
        history = [
            {"question": x["question"], "answer": x["answer"]} for x in s.history[-3:]
        ]
        result = evaluate_live(
            s.card_id,
            req.candidate_answer,
            question=s.pending_question,
            history=history,
            error_context=s.evaluation_context(),
            rubric=s.rubric,
        )
        if result.get("refusal") or result.get("abstained"):
            # An unavailable assessment is not a completed interview turn. Keep the
            # session available for retry while preserving the existing response.
            return {
                "session_id": s.session_id,
                "status": "needs_review",
                "human_review_required": True,
            }
        return s.add_assessment(req.candidate_answer, result)
    except (RuntimeError, ValueError, TypeError) as error:
        headers = failure_headers(
            error,
            card_id=s.card_id,
            criterion_ids=[c["id"] for c in s.rubric["criteria"]],
        )
        raise HTTPException(
            502,
            "LLM evaluation failed. Retry or request human review.",
            headers=headers,
        ) from None

    finally:
        lock.release()


@router.get("/session/{session_id}")
def session_info(session_id: str):
    s = SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(404, "Unknown/expired session")
    # internal only; previous answers omitted to reduce PII leakage
    return {
        "session_id": s.session_id,
        "card_id": s.card_id,
        "status": s.status,
        "pending_question": s.pending_question,
        "turns": len(s.history),
        "followups_asked": s.followups_asked,
        "human_review_required": True,
    }

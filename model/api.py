"""HTTP API for the single canonical interview model."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException
from interview.diagnostics import failure_headers
from interview.engine import (
    TopicSession,
    public_assessment,
    segmentation_messages_for,
    validate_data,
)
from interview.llm import LLMError, evaluate_live
from interview.registry import (
    AmbiguousCardSelection,
    CardNotFound,
    get_registry,
    public_card,
)
from pydantic import BaseModel, Field, model_validator


class AnswerRequest(BaseModel):
    card_id: str = Field(min_length=1, max_length=100)
    candidate_answer: str = Field(min_length=1, max_length=15000)


class StartRequest(BaseModel):
    card_id: str = Field(min_length=1, max_length=100)


class SessionAnswerRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    candidate_answer: str = Field(min_length=1, max_length=15000)


class SelectionRequest(BaseModel):
    card_id: str | None = Field(default=None, min_length=1, max_length=100)
    query: str = Field(default="", max_length=400)
    competency: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def has_selection_input(self):
        if not (self.card_id or self.query.strip() or (self.competency or "").strip()):
            raise ValueError("Specify card_id, query or competency")
        return self


app = FastAPI(
    title="chf.tech interview model",
    version="1.0.0",
    description="Single-version technical interview evaluation service.",
)
router = APIRouter()
sessions: dict[str, TopicSession] = {}


def entry_for(card_id: str):
    try:
        return get_registry().get(card_id)
    except CardNotFound:
        raise HTTPException(404, "Unknown card_id") from None


@router.get("/")
def root():
    return {"name": "chf.tech interview model", "status": "ok", "docs": "/docs"}


@router.get("/health")
def health():
    return {"status": "ok", **validate_data()}


@router.get("/cards")
def cards():
    registry = get_registry()
    return {"cards": registry.public_cards(), "registry_version": registry.version}


@router.post("/cards/select")
def select_card(request: SelectionRequest):
    try:
        entry = get_registry().select(
            card_id=request.card_id,
            query=request.query,
            competency=request.competency,
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


@router.post("/prepare")
def prepare(request: AnswerRequest):
    entry = entry_for(request.card_id)
    return {
        "card_id": request.card_id,
        "pipeline": "one_stage",
        "messages": segmentation_messages_for(
            request.card_id,
            request.candidate_answer,
            rubric=entry.rubric,
        ),
    }


@router.post("/evaluate")
def evaluate(request: AnswerRequest):
    entry = entry_for(request.card_id)
    try:
        result = evaluate_live(
            request.card_id,
            request.candidate_answer,
            rubric=entry.rubric,
        )
        return public_assessment(result)
    except LLMError as error:
        headers = failure_headers(
            error,
            card_id=request.card_id,
            criterion_ids=[criterion["id"] for criterion in entry.rubric["criteria"]],
        )
        raise HTTPException(
            502,
            "LLM evaluation failed. Retry or request human review.",
            headers=headers,
        ) from None


@router.post("/session/start")
def start_session(request: StartRequest):
    try:
        session = TopicSession(request.card_id)
    except CardNotFound:
        raise HTTPException(404, "Unknown card_id") from None
    sessions[session.session_id] = session
    return {
        "session_id": session.session_id,
        "card_id": session.card_id,
        "question": session.pending_question,
        "status": session.status,
        "max_followups": session.max_followups,
    }


@router.post("/session/answer")
def answer_session(request: SessionAnswerRequest):
    session = sessions.get(request.session_id)
    if session is None:
        raise HTTPException(404, "Unknown or expired session")
    if session.status != "in_progress":
        raise HTTPException(409, "Session already finished")

    try:
        result = evaluate_live(
            session.card_id,
            request.candidate_answer,
            question=session.pending_question,
            history=session.history[-3:],
            error_context=session.evaluation_context(),
            rubric=session.rubric,
        )
        if result.get("refusal") or result.get("abstained"):
            return {
                "session_id": session.session_id,
                "status": "needs_review",
                "human_review_required": True,
            }
        return session.add_assessment(request.candidate_answer, result)
    except LLMError as error:
        headers = failure_headers(
            error,
            card_id=session.card_id,
            criterion_ids=[criterion["id"] for criterion in session.rubric["criteria"]],
        )
        raise HTTPException(
            502,
            "LLM evaluation failed. Retry or request human review.",
            headers=headers,
        ) from None


@router.get("/session/{session_id}")
def session_info(session_id: str):
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Unknown or expired session")
    return {
        "session_id": session.session_id,
        "card_id": session.card_id,
        "status": session.status,
        "pending_question": session.pending_question,
        "turns": len(session.history),
        "followups_asked": session.followups_asked,
        "human_review_required": True,
    }


app.include_router(router)

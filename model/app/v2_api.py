"""V2 scoring/session endpoints layered on v1 RAG API. Local demo ONLY.

V1 owns the 25-card knowledge base; v2 PostgreSQL rubric is a separate,
expert-unreviewed experimental evaluator. No session is persisted to disk.
"""
from __future__ import annotations

from uuid import uuid4
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .kb import load_kb, get_card
from src.core import read_data
from src.llm_eval import evaluate
from src.session import InterviewSession

router = APIRouter(prefix="/v2", tags=["legacy v2: internal demo only"], deprecated=True)
RUBRIC_CARD_ID = "PG-QUERY-01"
CARDS = load_kb()
SESSIONS: dict[str, InterviewSession] = {}


class AnswerRequest(BaseModel):
    card_id: str = Field(default=RUBRIC_CARD_ID, max_length=100)
    candidate_answer: str = Field(min_length=1, max_length=12000)


class SessionAnswerRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    candidate_answer: str = Field(min_length=1, max_length=12000)


def check_supported(card_id: str):
    if not get_card(CARDS, card_id):
        raise HTTPException(status_code=404, detail="Card not found in 25-card RAG base")
    if card_id != RUBRIC_CARD_ID:
        raise HTTPException(status_code=400, detail="Scoring rubric exists only for PG-QUERY-01. Other cards support retrieval/questions only.")


def run_eval(answer: str, question: str | None = None, history=None):
    try:
        return evaluate(answer, question=question, history=history)
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        # Do not echo provider response or potentially sensitive inputs to users.
        raise HTTPException(status_code=502, detail=f"Evaluation failed: {type(exc).__name__}. Check API settings and model compatibility.") from exc


@router.get("/info")
def info():
    """Lists supported cards without revealing hidden rubric or model key."""
    return {
        "knowledge_cards": len(CARDS),
        "scoring_supported_card_ids": [RUBRIC_CARD_ID],
        "test_cases": len(read_data("eval_cases.json")),
        "scoring_review_status": read_data("rubric_postgresql.json")["status"],
        "sessions": "memory_only_not_persistent",
    }


@router.post("/evaluate")
def evaluate_single(req: AnswerRequest):
    check_supported(req.card_id)
    rubric = read_data("rubric_postgresql.json")
    result = run_eval(req.candidate_answer, question=rubric["question"])
    return {
        "card_id": req.card_id,
        "question": rubric["question"],
        "assessment": result,
        "human_review_required": True,
        "note": "Experimental technical scoring; no automatic hiring decision",
    }


@router.post("/session/start")
def session_start():
    session_id = str(uuid4())
    session = InterviewSession()
    SESSIONS[session_id] = session
    return {"session_id": session_id, "card_id": RUBRIC_CARD_ID, "question": session.pending_question,
            "status": session.status, "max_followups": 2}


@router.post("/session/answer")
def session_answer(req: SessionAnswerRequest):
    session = SESSIONS.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown/expired local session")
    if session.status != "in_progress":
        raise HTTPException(status_code=409, detail="Topic already finished")
    question = session.pending_question
    history = [(r["question"], r["answer"]) for r in session.transcript[-2:]]
    result = run_eval(req.candidate_answer, question=question, history=history)
    if result.get("needs_review"):
        return {"status": "needs_review", "question": None, "human_review_required": True,
                "note": "Model refused to score"}
    decision = session.record_answer(req.candidate_answer, result)
    return {
        "session_id": req.session_id,
        "answer_to_question": question,
        "score_for_latest_answer": result["score"],
        "cumulative_score": sum(c["points"] for c in session.criterion_evidence.values()),
        "followups_asked": session.followups_asked,
        "next_question": session.pending_question or None,
        "decision": decision,
        "status": session.status,
        "human_review_required": True,
    }

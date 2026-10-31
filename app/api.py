"""Внутренний FastAPI интерфейс. Запускайте только за backend/в доверенной сети."""
from __future__ import annotations
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from .kb import load_kb,get_card,public_metadata
from .retrieval import retrieve
from .interview import choose_question,evaluate_answer,prepare_messages
from .llm import LLMError,is_configured
from v3.registry import get_registry


@asynccontextmanager
async def lifespan(application):
    # Reject inconsistent catalog/rubric releases before accepting traffic.
    get_registry()
    yield

app = FastAPI(title="Python Backend RAG (internal demo)",version="0.1.0",
              description="Внутренний сервис RAG. v1/v2 — legacy; актуальный каталог и оценивание — v3. НЕ публиковать без авторизации.",
              lifespan=lifespan)
CARDS=load_kb()

class SearchRequest(BaseModel):
    query: str = Field(default="",max_length=400)
    competency: str | None = Field(default=None,max_length=120)
    limit: int = Field(default=3,ge=1,le=20)

class QuestionRequest(BaseModel):
    query: str = Field(default="",max_length=400)
    competency: str | None = Field(default=None,max_length=120)
    card_id: str | None = Field(default=None,max_length=100)
    candidate_answer: str | None = Field(default=None,max_length=12000)
    mode: Literal["template","llm"] = "template"

class EvaluateRequest(BaseModel):
    card_id: str = Field(min_length=1,max_length=100)
    candidate_answer: str = Field(min_length=1,max_length=12000)

class PromptRequest(BaseModel):
    card_id: str = Field(min_length=1,max_length=100)
    candidate_answer: str | None = Field(default=None,max_length=12000)
    task: Literal["question","evaluate"] = "question"


def selected_card(card_id: str | None, query: str, competency: str | None) -> dict:
    if card_id:
        card=get_card(CARDS,card_id)
        if card is None: raise HTTPException(404,"Неизвестный card_id")
        return card
    items=retrieve(CARDS,query,competency,1)
    if not items: raise HTTPException(404,"Не найдена релевантная карточка. Уточните компетенцию/тему")
    return get_card(CARDS,items[0]["id"])

@app.get("/health")
def health():
    return {"status":"ok","cards":len(CARDS),"llm_configured":is_configured()}

@app.get("/v1/competencies",deprecated=True,tags=['legacy v1'])
def competencies():
    return [public_metadata(card) for card in CARDS]

@app.post("/v1/retrieve",deprecated=True,tags=['legacy v1'])
def retrieve_api(data: SearchRequest):
    return {"results":retrieve(CARDS,data.query,data.competency,data.limit)}

@app.post("/v1/prepare",deprecated=True,tags=['legacy v1'])
def prepare_api(data: PromptRequest):
    """Контракт ML-инженеру: готовые role/content messages для собственного клиента LLM."""
    card=selected_card(data.card_id,"",None)
    try:messages=prepare_messages(card,data.candidate_answer,task=data.task)
    except ValueError as ex:raise HTTPException(400,str(ex)) from ex
    return {"card_id":card["id"],"review_status":card["review_status"],"messages":messages,
            "internal_only":True}

@app.post("/v1/question",deprecated=True,tags=['legacy v1'])
def question_api(data: QuestionRequest):
    card=selected_card(data.card_id,data.query,data.competency)
    try: return choose_question(card,data.candidate_answer,mode=data.mode)
    except LLMError as ex:raise HTTPException(502,str(ex)) from ex

@app.post("/v1/evaluate",deprecated=True,tags=['legacy v1'])
def evaluate_api(data: EvaluateRequest):
    card=selected_card(data.card_id,"",None)
    try:return evaluate_answer(card,data.candidate_answer)
    except LLMError as ex:raise HTTPException(502,str(ex)) from ex
    except ValueError as ex:raise HTTPException(400,str(ex)) from ex


# Unified evaluation and adaptive session endpoints for ALL 25 cards.
from .v3_api import router as v3_router
app.include_router(v3_router)

# Backward compatibility only: historical v2 PostgreSQL-only endpoints.
# For 25-card scoring use /v3/*, not /v2/*.
from .v2_api import router as legacy_v2_router
app.include_router(legacy_v2_router)

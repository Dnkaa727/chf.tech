"""HTTP entry point for the interview RAG service."""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI

from rag.registry import get_registry
from .routes import router


@asynccontextmanager
async def lifespan(application):
    # Reject inconsistent catalog/rubric releases before accepting traffic.
    get_registry()
    yield


app = FastAPI(
    title="Interview RAG",
    version="0.1.0",
    description="Local interview service: retrieve a topic, assess an answer and ask follow-ups.",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health")
def health():
    # Presence of configuration does not establish provider connectivity.
    key = (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
    model = os.getenv("LLM_MODEL", "gpt-4o-mini").strip()
    return {
        "status": "ok",
        "cards": len(get_registry().cards()),
        "llm_configured": bool(key and model),
    }

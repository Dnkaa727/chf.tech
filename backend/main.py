from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "model")

if MODEL_DIR not in sys.path:
    sys.path.insert(0, MODEL_DIR)

from v3.diagnostics import failure_headers
from v3.engine import TopicSession
from v3.llm import LLMError, evaluate_live
from v3.registry import CardNotFound, get_registry


class CreateConferenceRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    card_id: str | None = Field(default=None, max_length=100)
    query: str = Field(default="", max_length=400)
    competency: str | None = Field(default=None, max_length=120)


class SendMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=15000)


@dataclass
class Room:
    room_id: str
    candidate_name: str
    session: TopicSession
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    messages: list[dict[str, Any]] = field(default_factory=list)
    sockets: set[WebSocket] = field(default_factory=set)
    processing: bool = False
    ended: bool = False


rooms: dict[str, Room] = {}

app = FastAPI(
    title="chf.tech backend",
    version="1.0.0",
    description="Backend gateway between the frontend and the AI interview model.",
)


origins = os.getenv(
    "FRONTEND_ORIGINS",
    "http://127.0.0.1:5173,http://localhost:5173",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def make_message(
    author_id: str,
    author_name: str,
    author_kind: str,
    text: str,
) -> dict[str, Any]:
    return {
        "id": uuid4().hex,
        "authorId": author_id,
        "authorName": author_name,
        "authorKind": author_kind,
        "text": text,
        "sentAt": now_ms(),
    }


def make_participants(room: Room) -> list[dict[str, Any]]:
    return [
        {
            "id": "me",
            "name": room.candidate_name,
            "kind": "candidate",
            "roleLabel": "Кандидат",
            "cameraOn": True,
            "micOn": True,
            "speaking": False,
        },
        {
            "id": "ai-interviewer",
            "name": "ИИ-интервьюер",
            "kind": "ai",
            "roleLabel": "Техническое собеседование",
            "cameraOn": True,
            "micOn": True,
            "speaking": not room.ended,
        },
    ]


def interviewer_feedback(
    assessment: dict[str, Any],
    result: dict[str, Any],
) -> str:
    summary = assessment.get("summary")

    if isinstance(summary, str) and summary.strip():
        feedback = summary.strip()
    else:
        feedback = "Спасибо за ответ."

    action = result.get("action")

    if action == "needs_review":
        return f"{feedback}\nОтвет требует дополнительной проверки."

    if action == "insufficient_evidence":
        return f"{feedback}\nВ ответе недостаточно подтверждений."

    if action == "next_topic":
        return f"{feedback}\nПереходим к следующей теме."

    return feedback


def snapshot(room: Room) -> dict[str, Any]:
    return {
        "conferenceId": room.room_id,
        "state": {
            "status": "ended" if room.ended else "live",
        },
        "interviewerTyping": room.processing,
        "participants": make_participants(room),
        "content": {
            "me": {"type": "avatar"},
            "ai-interviewer": {"type": "avatar"},
        },
        "messages": room.messages,
        "session": {
            "sessionId": room.session.session_id,
            "cardId": room.session.card_id,
            "status": room.session.status,
            "pendingQuestion": room.session.pending_question,
            "followupsAsked": room.session.followups_asked,
        },
    }


async def broadcast(room: Room) -> None:
    if not room.sockets:
        return

    payload = snapshot(room)
    disconnected: list[WebSocket] = []

    for socket in list(room.sockets):
        try:
            await socket.send_json(payload)
        except Exception:
            disconnected.append(socket)

    for socket in disconnected:
        room.sockets.discard(socket)


def resolve_card(
    card_id: str | None,
    query: str,
    competency: str | None,
) -> str:
    registry = get_registry()

    if card_id:
        try:
            registry.get(card_id)
        except CardNotFound:
            raise HTTPException(404, "Unknown card_id") from None

        return card_id

    if not query.strip() and not (competency or "").strip():
        cards = registry.public_cards()

        if not cards:
            raise HTTPException(500, "No interview cards configured")

        return cards[0]["card_id"]

    try:
        entry = registry.select(
            query=query,
            competency=competency,
        )
        return entry.card["id"]
    except Exception as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unable to select an interview card: {error}",
        ) from error


def get_room(conference_id: str) -> Room:
    room = rooms.get(conference_id)

    if room is None:
        raise HTTPException(404, "Conference not found")

    return room


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "chf.tech backend",
        "status": "ok",
        "websocket": "/api/conferences/{conference_id}/ws",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": os.getenv("LLM_MODEL", ""),
        "llm_base_url": os.getenv("LLM_BASE_URL", ""),
        "active_conferences": len(rooms),
    }


@app.get("/api/cards")
def cards() -> dict[str, Any]:
    registry = get_registry()

    return {
        "cards": registry.public_cards(),
        "registry_version": registry.version,
    }


@app.post("/api/conferences")
def create_conference(
    request: CreateConferenceRequest,
) -> dict[str, Any]:
    card_id = resolve_card(
        request.card_id,
        request.query,
        request.competency,
    )

    try:
        session = TopicSession(card_id)
    except CardNotFound:
        raise HTTPException(404, "Unknown card_id") from None

    room = Room(
        room_id=uuid4().hex,
        candidate_name=request.name.strip(),
        session=session,
    )

    room.messages.append(
        make_message(
            "ai-interviewer",
            "ИИ-интервьюер",
            "ai",
            session.pending_question,
        )
    )

    rooms[room.room_id] = room

    return snapshot(room)


@app.get("/api/conferences/{conference_id}")
def conference_state(conference_id: str) -> dict[str, Any]:
    return snapshot(get_room(conference_id))


@app.websocket("/api/conferences/{conference_id}/ws")
async def conference_websocket(
    websocket: WebSocket,
    conference_id: str,
) -> None:
    room = rooms.get(conference_id)

    if room is None:
        await websocket.close(
            code=1008,
            reason="Conference not found",
        )
        return

    await websocket.accept()
    room.sockets.add(websocket)

    try:
        await websocket.send_json(snapshot(room))

        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        room.sockets.discard(websocket)

    except Exception:
        room.sockets.discard(websocket)

        try:
            await websocket.close()
        except Exception:
            pass


@app.post("/api/conferences/{conference_id}/messages")
async def send_message(
    conference_id: str,
    request: SendMessageRequest,
) -> dict[str, Any]:
    room = get_room(conference_id)

    if room.ended:
        raise HTTPException(409, "Conference already ended")

    if room.session.status != "in_progress":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "session_finished",
                "message": "Interview session already finished",
                "session_status": room.session.status,
            },
        )

    if room.processing:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "message_in_progress",
                "message": "Previous answer is still being processed",
            },
        )

    room.processing = True
    text = request.text.strip()

    try:
        room.messages.append(
            make_message(
                "me",
                room.candidate_name,
                "candidate",
                text,
            )
        )

        await broadcast(room)

        history = [
            {
                "question": item["question"],
                "answer": item["answer"],
            }
            for item in room.session.history[-3:]
        ]

        assessment = await asyncio.to_thread(
            evaluate_live,
            room.session.card_id,
            text,
            question=room.session.pending_question,
            history=history,
            error_context=room.session.evaluation_context(),
            rubric=room.session.rubric,
        )

        if assessment.get("refusal") or assessment.get("abstained"):
            room.messages.append(
                make_message(
                    "ai-interviewer",
                    "ИИ-интервьюер",
                    "ai",
                    "Ответ передан на проверку человеком.",
                )
            )

            await broadcast(room)
            return snapshot(room)

        result = room.session.add_assessment(
            text,
            assessment,
        )

        room.messages.append(
            make_message(
                "ai-interviewer",
                "ИИ-интервьюер",
                "ai",
                interviewer_feedback(assessment, result),
            )
        )

        next_question = result.get("next_question")

        if next_question:
            room.messages.append(
                make_message(
                    "ai-interviewer",
                    "ИИ-интервьюер",
                    "ai",
                    next_question,
                )
            )
        else:
            room.messages.append(
                make_message(
                    "ai-interviewer",
                    "ИИ-интервьюер",
                    "ai",
                    "Спасибо. Тема собеседования завершена.",
                )
            )

        return snapshot(room)

    except LLMError as error:
        criterion_ids = [
            criterion["id"] for criterion in room.session.rubric["criteria"]
        ]

        headers = failure_headers(
            error,
            card_id=room.session.card_id,
            criterion_ids=criterion_ids,
        )

        raise HTTPException(
            status_code=502,
            detail="LLM evaluation failed. Retry the answer.",
            headers=headers,
        ) from None

    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=str(error),
        ) from error

    except TypeError as error:
        raise HTTPException(
            status_code=500,
            detail="Invalid evaluation result from backend",
        ) from error

    finally:
        room.processing = False
        await broadcast(room)


@app.delete("/api/conferences/{conference_id}")
async def leave_conference(
    conference_id: str,
) -> dict[str, Any]:
    room = get_room(conference_id)

    room.ended = True
    room.session.status = "ended"

    await broadcast(room)

    for socket in list(room.sockets):
        try:
            await socket.close()
        except Exception:
            pass

    room.sockets.clear()

    return snapshot(room)

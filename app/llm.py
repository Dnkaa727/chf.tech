"""Минимальный клиент OpenAI-compatible /chat/completions без SDK.

Работает с провайдером, поддерживающим такой HTTP интерфейс.
Совместимость отдельных полей ответа/моделей нужно проверять у провайдера.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error


class LLMError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(os.getenv("LLM_MODEL", "").strip() and os.getenv("LLM_API_KEY", "").strip())


def chat(messages: list[dict]) -> str:
    base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    model = os.getenv("LLM_MODEL", "").strip()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not model or not api_key:
        raise LLMError("Нужны LLM_MODEL и LLM_API_KEY (см. .env.example / README)")
    if not (base.startswith("https://") or base.startswith("http://localhost") or base.startswith("http://127.0.0.1")):
        raise LLMError("Для внешнего API требуется HTTPS. Для локального разрешён http://localhost")
    payload = json.dumps({"model":model,"messages":messages},ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/chat/completions",data=payload,
        headers={"Content-Type":"application/json","Authorization":f"Bearer {api_key}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request,timeout=int(os.getenv("LLM_TIMEOUT_SECONDS","40"))) as response:
            body = json.load(response)
    except urllib.error.HTTPError as ex:
        raise LLMError(f"LLM API вернул HTTP {ex.code}; проверь адрес, модель, ключ и квоты") from ex
    except (urllib.error.URLError, TimeoutError) as ex:
        raise LLMError(f"Нет ответа от LLM API: {type(ex).__name__}") from ex
    try:
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content,str) or not content.strip():
            raise ValueError("empty content")
        return content
    except (ValueError, KeyError, IndexError, TypeError) as ex:
        raise LLMError("LLM API вернул неожиданный формат ответа") from ex


def parse_json_response(raw: str) -> dict:
    """Ждём объект JSON. Иногда провайдер оборачивает JSON в markdown fence."""
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    try:
        result=json.loads(text.strip())
        if not isinstance(result,dict):
            raise ValueError("not an object")
        return result
    except (json.JSONDecodeError,ValueError) as ex:
        raise LLMError("LLM не вернула корректный JSON-объект; повторите или измените промпт") from ex

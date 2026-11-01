"""GenAPI Silero speech. Credentials stay server-side; each message is submitted at most once."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import quote, urljoin, urlsplit

import httpx

logger = logging.getLogger(__name__)

ENDPOINT = "https://api.gen-api.ru/api/v1/networks/silero-tts"
STATUS_ENDPOINT = "https://api.gen-api.ru/api/v1/request/get/"
POLL_INTERVAL = 1.0
MAX_AUDIO_BYTES = 10 * 1024 * 1024
CACHE_BYTES = 32 * 1024 * 1024


class SpeechError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class SpeechJob:
    submitted: bool = False
    request_id: str | None = None
    audio_url: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)
    blocked_error: SpeechError | None = field(default=None, repr=False)
    phase: str = "idle"
    provider_http: int | None = None


def audio_url(output) -> str:
    """Handle a single audio URL, a result list, or an explicitly named audio field."""
    if isinstance(output, str) and output.startswith("https://"):
        return output
    if isinstance(output, list) and len(output) == 1:
        return audio_url(output[0])
    if isinstance(output, dict):
        for key in ("audio", "audio_url", "url", "file"):
            if key in output:
                return audio_url(output[key])
    raise SpeechError("GenAPI вернул неизвестный формат аудио. Продолжи интервью в чате.")


def validation_fields(response: httpx.Response) -> list[str]:
    """Extract only known parameter names; provider values may contain private data."""
    known = {"text", "speaker", "sample_rate", "format", "lang", "callback_url", "is_sync", "put_accent", "put_yo", "ssml"}
    found = set()
    try:
        body = response.json()
    except ValueError:
        return []
    def visit(value, depth=0):
        if depth > 6:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if key in known:
                    found.add(key)
                # Locations are metadata, not free-form messages or echoed input.
                if key in ("loc", "field", "param"):
                    for name in item if isinstance(item, list) else [item]:
                        if isinstance(name, str) and name in known:
                            found.add(name)
                if key in ("errors", "detail", "validation_errors"):
                    visit(item, depth + 1)
        elif isinstance(value, list):
            for item in value[:30]:
                visit(item, depth + 1)
    visit(body)
    return sorted(found)


async def validate_audio_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise SpeechError("GenAPI вернул недопустимый адрес аудио.") from None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or port not in (None, 443):
        raise SpeechError("GenAPI вернул недопустимый адрес аудио.")
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise SpeechError("GenAPI вернул недопустимый адрес аудио.")
    except (OSError, ValueError):
        raise SpeechError("Не удалось проверить адрес аудио GenAPI.") from None


def audio_type(data: bytes) -> str:
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"ID3") or (len(data) > 2 and data[0] == 255 and data[1] & 224 == 224):
        return "audio/mpeg"
    raise SpeechError("Сервис озвучивания вернул файл, который не является аудио.")


class GenApiSpeech:
    def __init__(self, client_factory=httpx.AsyncClient):
        self.client_factory = client_factory
        self.cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self.cache_size = 0
        self.slots = asyncio.Semaphore(2)

    async def get(self, cache_key: str, text: str, job: SpeechJob) -> tuple[bytes, str]:
        cached = self.cache.get(cache_key)
        if cached is not None:
            self.cache.move_to_end(cache_key)
            return cached
        if job.task is None or job.task.done():
            job.task = asyncio.create_task(self._run(cache_key, text, job))
            # Release task results so evicted audio is not retained through completed tasks.
            # Consume errors even if the browser disconnected while synthesis was running.
            def completed(task):
                if job.task is task:
                    job.task = None
                if not task.cancelled():
                    task.exception()
            job.task.add_done_callback(completed)
        return await asyncio.shield(job.task)

    async def _run(self, cache_key: str, text: str, job: SpeechJob) -> tuple[bytes, str]:
        # Preserve the original cause when submission may have succeeded without an ID.
        if job.blocked_error is not None:
            raise job.blocked_error
        try:
            return await self._generate(cache_key, text, job)
        except SpeechError as error:
            if job.submitted and not job.request_id and not job.audio_url:
                job.blocked_error = error
            # Only controlled messages and numeric IDs are logged, never provider bodies,
            # headers, credentials, signed audio URLs or interview text.
            request_id = job.request_id if job.request_id and job.request_id.isdecimal() else "unknown"
            logger.warning("GenAPI TTS failed: phase=%s http=%s request_id=%s reason=%s",
                           job.phase, job.provider_http, request_id, error)
            raise

    async def _generate(self, cache_key: str, text: str, job: SpeechJob) -> tuple[bytes, str]:
        key = os.getenv("GENAPI_API_KEY", "").strip()
        if not key:
            raise SpeechError("Озвучивание не настроено: добавь GENAPI_API_KEY на сервере.", 503)
        if not text.strip() or len(text) > 5000:
            raise SpeechError("Эта реплика слишком длинная для озвучивания. Прочитай её в чате.", 422)
        try:
            rate = int(os.getenv("GENAPI_TTS_SAMPLE_RATE", "24000"))
            if rate not in (8000, 24000, 48000):
                raise ValueError()
        except ValueError:
            raise SpeechError("Проверь настройку GENAPI_TTS_SAMPLE_RATE на сервере.", 503) from None
        payload = {
            "is_sync": False, "text": text, "callback_url": None,
            "speaker": os.getenv("GENAPI_TTS_SPEAKER", "xenia"),
            "sample_rate": rate, "lang": "ru", "put_accent": True,
            "put_yo": True, "ssml": False, "format": "ogg",
        }
        try:
            async with asyncio.timeout(90), self.slots:
                async with self.client_factory(timeout=80, follow_redirects=False) as client:
                    if job.audio_url is None:
                        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
                        if job.request_id:
                            job.phase = "poll"
                            job.provider_http = None
                            response = await client.get(STATUS_ENDPOINT + quote(job.request_id, safe=""), headers=headers)
                            body = self._response(response, job)
                        else:
                            if job.submitted:
                                raise SpeechError("Запрос уже отправлен в GenAPI, но его ID не получен. Проверь запрос в кабинете GenAPI.", 503)
                            job.submitted = True
                            job.phase = "submit"
                            job.provider_http = None
                            response = await client.post(ENDPOINT, json=payload, headers=headers)
                            body = self._response(response, job, submission=True)
                            if body.get("request_id") is not None:
                                job.request_id = str(body["request_id"])
                        while body.get("status") in ("starting", "processing", "queued", "pending", "running"):
                            if not job.request_id:
                                raise SpeechError("GenAPI не вернул ID задачи озвучивания.")
                            await asyncio.sleep(POLL_INTERVAL)
                            job.phase = "poll"
                            job.provider_http = None
                            response = await client.get(STATUS_ENDPOINT + quote(job.request_id, safe=""), headers=headers)
                            body = self._response(response, job)
                        if body.get("status") in ("failed", "error"):
                            raise SpeechError("GenAPI не смог создать аудио. Проверь запрос в кабинете сервиса.")
                        if body.get("status") != "success":
                            raise SpeechError("GenAPI вернул неизвестный статус озвучивания.")
                        job.audio_url = audio_url(body.get("output"))
                    job.phase = "download"
                    job.provider_http = None
                    data = await self._download(client, job.audio_url)
                    result = (data, audio_type(data))
                    while self.cache and self.cache_size + len(data) > CACHE_BYTES:
                        _, removed = self.cache.popitem(last=False)
                        self.cache_size -= len(removed[0])
                    self.cache[cache_key] = result
                    self.cache_size += len(data)
                    return result
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # Connection/handshake failed before an HTTP request could be sent.
            if job.phase == "submit" and not job.request_id:
                job.submitted = False
            raise SpeechError("Не удалось установить соединение с GenAPI или хранилищем аудио. Проверь доступ к сети и попробуй ещё раз.") from None
        except (TimeoutError, httpx.TimeoutException):
            raise SpeechError("GenAPI не успел подготовить голос. Попробуй позже; повторная отправка текста автоматически не выполняется.", 504) from None
        except httpx.HTTPError:
            raise SpeechError("Не удалось связаться с GenAPI или скачать аудио. Попробуй позже.") from None

    @staticmethod
    def _response(response: httpx.Response, job: SpeechJob, submission: bool = False) -> dict:
        job.provider_http = response.status_code
        # Validation failures are explicit rejections, not possibly accepted paid jobs.
        if response.status_code in (400, 401, 403, 402, 422, 429) and submission:
            job.submitted = False
        if response.status_code in (401, 403):
            raise SpeechError("GenAPI отклонил ключ. Проверь GENAPI_API_KEY на сервере.", 503)
        if response.status_code == 402:
            raise SpeechError("Недостаточно средств для озвучивания в GenAPI.", 503)
        if response.status_code == 429:
            raise SpeechError("Достигнут лимит GenAPI. Попробуй озвучить позже.", 429)
        if response.status_code in (400, 422):
            fields = validation_fields(response)
            suffix = f"; поля: {', '.join(fields)}" if fields else ""
            raise SpeechError(f"GenAPI отклонил параметры озвучивания (HTTP {response.status_code}{suffix}).")
        if response.status_code >= 400:
            raise SpeechError(f"GenAPI не смог обработать запрос озвучивания (HTTP {response.status_code}).")
        try:
            body = response.json()
        except ValueError:
            raise SpeechError("GenAPI вернул некорректный ответ.") from None
        if not isinstance(body, dict):
            raise SpeechError("GenAPI вернул некорректный ответ.")
        return body

    async def _download(self, client: httpx.AsyncClient, url: str) -> bytes:
        # Do not forward the API bearer token to storage hosts, including redirects.
        for _ in range(4):
            await validate_audio_url(url)
            async with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                if response.status_code != 200:
                    raise SpeechError("Не удалось скачать аудио GenAPI. Попробуй позже.")
                chunks = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        raise SpeechError("Аудиофайл слишком большой для воспроизведения.")
                    chunks.append(chunk)
                return b"".join(chunks)
        raise SpeechError("Не удалось получить конечный адрес аудио GenAPI.")

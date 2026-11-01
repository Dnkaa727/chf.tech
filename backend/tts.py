"""GenAPI Silero speech. Credentials stay server-side; each message is submitted at most once."""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import quote, urljoin, urlsplit

import httpx

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
            job.task = asyncio.create_task(self._generate(cache_key, text, job))
            # Release task results so evicted audio is not retained through completed tasks.
            # Consume errors even if the browser disconnected while synthesis was running.
            def completed(task):
                if job.task is task:
                    job.task = None
                if not task.cancelled():
                    task.exception()
            job.task.add_done_callback(completed)
        return await asyncio.shield(job.task)

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
                            response = await client.get(STATUS_ENDPOINT + quote(job.request_id, safe=""), headers=headers)
                            body = self._response(response, job)
                        else:
                            if job.submitted:
                                raise SpeechError("Запрос уже отправлен в GenAPI, но его ID не получен. Проверь запрос в кабинете GenAPI.", 503)
                            job.submitted = True
                            response = await client.post(ENDPOINT, json=payload, headers=headers)
                            body = self._response(response, job, submission=True)
                            if body.get("request_id") is not None:
                                job.request_id = str(body["request_id"])
                        while body.get("status") in ("starting", "processing", "queued", "pending", "running"):
                            if not job.request_id:
                                raise SpeechError("GenAPI не вернул ID задачи озвучивания.")
                            await asyncio.sleep(POLL_INTERVAL)
                            response = await client.get(STATUS_ENDPOINT + quote(job.request_id, safe=""), headers=headers)
                            body = self._response(response, job)
                        if body.get("status") in ("failed", "error"):
                            raise SpeechError("GenAPI не смог создать аудио. Проверь запрос в кабинете сервиса.")
                        if body.get("status") != "success":
                            raise SpeechError("GenAPI вернул неизвестный статус озвучивания.")
                        job.audio_url = audio_url(body.get("output"))
                    data = await self._download(client, job.audio_url)
                    result = (data, audio_type(data))
                    while self.cache and self.cache_size + len(data) > CACHE_BYTES:
                        _, removed = self.cache.popitem(last=False)
                        self.cache_size -= len(removed[0])
                    self.cache[cache_key] = result
                    self.cache_size += len(data)
                    return result
        except (TimeoutError, httpx.TimeoutException):
            raise SpeechError("GenAPI не успел подготовить голос. Попробуй позже; повторная отправка текста автоматически не выполняется.", 504) from None
        except httpx.HTTPError:
            raise SpeechError("Не удалось связаться с GenAPI или скачать аудио. Попробуй позже.") from None

    @staticmethod
    def _response(response: httpx.Response, job: SpeechJob, submission: bool = False) -> dict:
        # Only an explicitly rejected submission may be submitted again after configuration is fixed.
        if response.status_code in (401, 403, 402, 429) and submission:
            job.submitted = False
        if response.status_code in (401, 403):
            raise SpeechError("GenAPI отклонил ключ. Проверь GENAPI_API_KEY на сервере.", 503)
        if response.status_code == 402:
            raise SpeechError("Недостаточно средств для озвучивания в GenAPI.", 503)
        if response.status_code == 429:
            raise SpeechError("Достигнут лимит GenAPI. Попробуй озвучить позже.", 429)
        if response.status_code >= 400:
            raise SpeechError("GenAPI не смог обработать запрос озвучивания. Попробуй позже.")
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

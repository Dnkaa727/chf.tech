# Модуль технического интервью

Eдиная модель ИИ-интервьюера для технических собеседований.
Она содержит каталог из 25 тем, рубрики оценки, поиск темы, сессии интервью и двухэтапную проверку ответов кандидата с доказательствами и красные флаги.

## Стек

- Python 3.12+
- FastAPI и Uvicorn
- Pydantic 2
- OpenAI-совместимый API для LLM

## Локальный запуск модели

Из корня репозитория:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r model/requirements.txt
PYTHONPATH=model uvicorn api:app --app-dir model --reload --port 8000
```

После запуска документация API доступна по адресу `http://localhost:8000/docs`.

Для работы модели задайте переменные окружения:

```bash
export LLM_API_KEY="ваш-ключ"
export LLM_BASE_URL="https://api.hubris.pw/v1"
export LLM_MODEL="openai/gpt-4o-mini"
export LLM_TIMEOUT_SECONDS="75"
export LLM_JSON_MODE="schema"
export LLM_MESSAGE_MODE="system_user"
```

Без `LLM_API_KEY` доступны каталог, выбор карточек, старт сессии и подготовка
сообщений, но оценка ответа работать не будет.

## Конечные точки REST API

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/health` | Проверка состояния и данных |
| `GET` | `/cards` | Получить каталог тем |
| `POST` | `/cards/select` | Выбрать тему по ID, запросу или компетенции |
| `POST` | `/prepare` | Подготовить сообщения для первого этапа оценки |
| `POST` | `/evaluate` | Оценить один ответ |
| `POST` | `/session/start` | Начать интервью по теме |
| `POST` | `/session/answer` | Передать ответ в активную сессию |
| `GET` | `/session/{session_id}` | Получить состояние сессии |



# Техническое handoff для ML-инженера

> Legacy v1: документ описывает исторический интерфейс. Новая интеграция использует
> [реестр и выбор карточек v3](REGISTRY_V3_RU.md). Историческая KB сохранена в
> `data/legacy/knowledge_base_v1.json`.

## Точка интеграции

**Самый простой вариант:** ваш существующий voice/LLM backend делает HTTP запросы к RAG API:

```text
STT transcript ─→ voice/backend orchestrator ──POST /v1/retrieve────────→ RAG
                            │                  POST /v1/prepare(card_id) → RAG
                            ↓ messages
                      ваша LLM через API
                            ↓ question
                    backend → TTS → кандидат
```

Для быстрого MVP backend может обращаться сразу к `POST /v1/question` с `mode=llm`, тогда наш сервис сам вызывает совместимый LLM endpoint.

**Важно:** сервис не хранит состояние собеседования. Оркестратор должен помнить `interview_id`, уже заданные `card_id`, число уточнений, транскрипты и пользовательские согласия. Не хранить ПДн в открытых логах.

## Примеры запросов / ответов

`POST /v1/retrieve`

```json
{"query":"почему PostgreSQL не использует индекс", "competency":"PostgreSQL", "limit":3}
```

Ответ содержит `results` с `id`, `score`, `matches`, `source_urls`, `review_status`. Это **ранжирование**, не вероятность корректности.

`POST /v1/prepare`

```json
{"card_id":"PG-QUERY-01", "candidate_answer":"Индексы ускоряют чтение", "task":"evaluate"}
```

Ответ: `{ "card_id": "...", "messages": [{"role":"system","content":"..."},{"role":"user","content":"..."}], "review_status":"..." }`.

**Контракт `messages`:** стандартный массив для Chat Completions; если модель использует другой API, преобразуйте `system/user` в формат провайдера на уровне ML adapter. Не переносите business logic и RAG в адаптер.

`POST /v1/question`:

```json
{"card_id":"PG-QUERY-01", "candidate_answer":"Индексы всегда ускоряют запросы", "mode":"llm"}
```

Ответ: `card_id`, `question`, `mode`, `review_status`.

`POST /v1/evaluate`:

```json
{"card_id":"PG-QUERY-01", "candidate_answer":"Я проверил план в EXPLAIN"}
```

Ответ: `confirmed=[{criterion_id,quote}]`, `unconfirmed=[criterion_id]`, `followup`, `notes`, `score=null`, `human_review_required=true`.

Legacy `criterion_id` ссылается на `data/legacy/knowledge_base_v1.json`.
Актуальные критерии v3 находятся только в `data/rubrics_all_25.json`.

## Требования к LLM provider adapter

- Совместимый HTTP API: `POST <LLM_BASE_URL>/chat/completions`.
- JSON body `{"model":"...","messages":[...]}`; Bearer API key.
- Ожидается `choices[0].message.content` с JSON **объектом**.
- При проблемах сети и неправильном формате возвращать ошибку, а не фиктивную оценку.
- Не записывать ключи, аудио, транскрипции, чужие ПДн в логи.
- Реализацию заменить в `app/llm.py`; функции `chat(messages)` и `parse_json_response(raw)` образуют минимальный внутренний контракт.

## План оценки качества

1. Провести ревизию и утвердить карточки с разработчиком. Хранить точные версии критериев.
2. Для 5–10 ключевых тем собрать по 3 типа синтетических ответов: сильный/частичный/неверный (без личных данных).
3. Ручная эталонная разметка с дословными цитатами и сопоставлением критериев.
4. Проверить `retrieval recall@3`, долю неверно найденных карточек, валидность JSON и цитат, качество уточнений.
5. Сравнить одну API-модель с self-hosted моделью Qwen на идентичном датасете, включая задержку и стоимость.

## Ограничения доступа

`/v1/prepare` выдаёт внутренние критерии оценки! API держать за backend, не отдавать напрямую кандидату, не включать публичные CORS/открытую авторизацию. Настоящие банковские данные передавать только в согласованном контуре.

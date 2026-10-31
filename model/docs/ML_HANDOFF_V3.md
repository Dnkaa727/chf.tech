# ML-engineer handoff: all 25 rubrics

**Entry point:** `v3/engine.py` (model-independent), `v3/llm.py` (model adapter).

Catalog/rubric registry and React-facing selection: [REGISTRY_V3_RU.md](REGISTRY_V3_RU.md).
The catalog has no scoring criteria. Use `GET /v3/cards`, `POST /v3/cards/select`,
then the existing `POST /v3/session/start` with the selected `card_id`.
Ambiguous selection returns HTTP 409 with public candidates.

### Inference contract

По умолчанию `evaluate_live()` использует `LLM_PIPELINE_MODE=two_stage` и выполняет два вызова Chat Completions:

1. `segmentation_messages_for()` / `segmentation_schema_for()` извлекают атомарные смысловые фрагменты и связывают их с одним или несколькими критериями. Эта связь означает релевантность, а не правильность.
2. `validate_segments()` проверяет цитаты по исходному ответу, восстанавливает точные source spans и присваивает серверные ID `S001`, `S002`, ...
3. `scoring_messages_for()` / `scoring_schema_for()` передают полный ответ, рубрику и все сегменты второму вызову. Он распределяет каждый связанный фрагмент по `supporting`, `partially_supporting`, `contradicting` или `neutral`, затем выставляет баллы.
4. `check_segmented_output()` проверяет, что каждый сегмент просмотрен, все связанные с критерием фрагменты классифицированы ровно один раз, а ссылки существуют. Цитаты в результате восстанавливаются Python по segment ID.

В критериях результата сохраняются `points`, `quote`, `reason` и массив `evidence` с несколькими исходными фрагментами. `quote` — основная цитата для совместимости.

Для baseline-сравнения доступен старый одновызовный путь: `LLM_PIPELINE_MODE=one_stage`. Он использует `messages_for()`, `schema_for()` и `check_output()`. Оба режима работают по одному snapshot выбранной рубрики.

`LLM_MESSAGE_MODE=system_user` объединяет системные и внутренние инструкции в `system` и оставляет сообщение кандидата в `user`; это полезно для совместимых API-шлюзов, не принимающих роль `developer`.

Подробное описание и команды: `docs/TWO_STAGE_PIPELINE_RU.md`.

### REST endpoints

- `GET /v3/info`, `GET /v3/rubrics`
- `POST /v3/prepare` `{ "card_id": "PY-ASYNC-01", "candidate_answer": "..." }`
- `POST /v3/evaluate` same payload, real LLM API call
- `POST /v3/session/start` `{ "card_id": "PG-QUERY-01" }`
- `POST /v3/session/answer` `{ "session_id": "<returned>", "candidate_answer": "..." }`

`/v1/*` and `/v2/*` are deprecated legacy adapters. Their historical KB is preserved
in `data/legacy/knowledge_base_v1.json`. **Use `/v3/*` for new selection and scoring.**

### Responsibilities and restrictions

- Backend chooses the `card_id` based on vacancy, topic order and previously covered skills; v3 manages a *single topic* with up to two follow-ups.
- `v3.registry` validates and caches all 25 catalog/rubric pairs. Each topic pins its
  rubric version/hash. Pass `rubric=session.rubric` to `evaluate_live` for session
  calls; prompt, schema and validation must use that same snapshot.
- Interview history is in-memory only and lost on restart; no multi-user auth/session persistence. Do not expose it publicly.
- Every grade is a **provisional technical score**, not an HR decision. Human review required.
- Do not pass expected case labels (`gold_criteria`, `expected_flags`) to the LLM; v3 `segmentation_messages_for` / `scoring_messages_for` use only rubrics, current answer and server-owned session state.
- Offline mock uses `gold_fixture` and cannot measure model accuracy. Real tests: `py run.py live-one <ID> <kind>`; `live-six` tests one topic, `live-redteam` tests 2 security/irrelevance cases; `live-all --confirm-cost` evaluates 150 answers and makes 300 provider calls in `two_stage` mode (150 in `one_stage`).
- For external provider: verify exact base URL, model name, and Structured Outputs support; keys must not appear in code/logs/messages.
- Track `card_id`, rubric `version`, model ID, prompt version, token counts, time/latency, source data version, and expert-approved labels for reproducibility.

Sources: original `knowledge_base.json` retains vacancy provenance. Rubric docs URLs are suggestions for later expert review, not proven validations.

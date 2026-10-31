# Исправление источника 502 в двухэтапной оценке v3

## Что исправлено

### 1. Убрана динамическая схема с пустыми объектами

Раньше Stage 2 строил для каждого критерия `segment_assessments` как JSON-объект, чьи ключи — ID сегментов, направленных в этот критерий на Stage 1. Если Stage 1 не связал ни одного сегмента с критерием, провайдер получал вложенную схему:

```json
{"type":"object","properties":{},"required":[],"additionalProperties":false}
```

Это нежелательная форма для совместимых шлюзов Structured Outputs: часть шлюзов отвергает или некорректно обрабатывает динамические пустые object-схемы. Это особенно вероятно на частичных ответах, в которых один или несколько критериев не получили сегментов.

Теперь `segment_assessments` всегда массив объектов:

```json
[
  {"segment_id":"S001","relation":"supports"},
  {"segment_id":"S003","relation":"partially_supports"}
]
```

Если фрагментов для критерия нет, Stage 2 возвращает `[]`. Python проверяет, что массив содержит ровно все и только сегменты, связанные с критерием, что ID не повторяются и что relation допустим. Пустой критерий не превращается в ненулевой балл.

### 2. Устранена потеря причины provider HTTP error

Раньше HTTP-ошибка провайдера превращалась в общий `provider_http_error`; тело ответа намеренно выбрасывалось целиком. Поэтому невозможно было отличить, например, `invalid_json_schema` от `model_not_found` или ошибки доступа.

Теперь сервер извлекает из JSON-ошибки только ограниченные поля: `code`, `type`, `param` и `x-request-id`. Свободный текст `message`, тело ответа, промпт и ключ API не логируются и не отправляются клиенту.

Ответ 502 может включать диагностические заголовки:

- `X-LLM-Stage`: `segmentation`, `scoring` или `evaluation`;
- `X-LLM-Provider-Status`: HTTP-статус провайдера;
- `X-LLM-Provider-Code`: безопасный код провайдера, например `invalid_json_schema`;
- `X-LLM-Provider-Type`: тип ошибки;
- `X-LLM-Provider-Param`: поле запроса, которое провайдер отклонил;
- `X-LLM-Provider-Request-ID`: request ID провайдера;
- `X-LLM-Error-Code` и `X-Request-ID`: локальная диагностика сервера.

Те же безопасные поля записываются в серверный лог `rag.v3.llm`.

## Что не менялось

- Публичный формат ответа `POST /v3/evaluate`.
- Пять критериев, их anchors и правила начисления баллов.
- Проверка точности цитат и покрытия сегментов.
- Red Flags, `error_updates`, `resolutions` и сессионная логика.
- Модель, URL провайдера и параметры доступа.
- Этот патч не добавляет повторные LLM-вызовы и не увеличивает число запросов.

Внутренний JSON Stage 2 изменён: `segment_assessments` теперь массив. Это не публичный API-контракт — его формирует и потребляет сам backend.

## Установка

Из корня `D:\RAG_BACKEND_ALL_25` в PowerShell:

```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
Copy-Item .\v3\engine.py ".\v3\engine.py.$stamp.bak"
Copy-Item .\v3\llm.py ".\v3\llm.py.$stamp.bak"
Copy-Item .\v3\diagnostics.py ".\v3\diagnostics.py.$stamp.bak"

Expand-Archive .\RAG_BACKEND_ALL_25_ROOT_CAUSE_PATCH.zip .\_root_cause_patch -Force
Copy-Item .\_root_cause_patch\v3\engine.py .\v3\engine.py -Force
Copy-Item .\_root_cause_patch\v3\llm.py .\v3\llm.py -Force
Copy-Item .\_root_cause_patch\v3\diagnostics.py .\v3\diagnostics.py -Force
Copy-Item .\_root_cause_patch\tests\test_v3_root_cause_schema.py .\tests\ -Force
```

Если тестовые файлы из архива уже есть в проекте, обновите их версиями из папки `tests` архива, чтобы тесты проверяли новый внутренний формат `segment_assessments`.

Проверка:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_v3_root_cause_schema.py tests\test_v3_two_stage.py tests\test_v3_red_flag_evidence.py tests\test_v3_red_flag_checklist.py tests\test_v3_resolution_guard.py tests\test_v3_error_transport.py tests\test_v3_llm_validation.py tests\test_v3_all25.py tests\test_pg_logic_patch.py -q
```

После этого перезапустите сервер.

## Как подтвердить точную первопричину

Повторите исходный `PG-TX-01` partial. Если раньше провайдер отклонял пустую JSON Schema, проблема должна исчезнуть. Если 502 останется, посмотрите серверный лог `llm_evaluation_failed` или заголовки ответа. Комбинация вроде:

```text
X-LLM-Stage: scoring
X-LLM-Provider-Status: 400
X-LLM-Provider-Code: invalid_json_schema
X-LLM-Provider-Param: response_format.json_schema.schema
```

подтвердит отказ схемы со стороны провайдера. Если код будет другим, теперь он будет виден без показа свободного текста ошибки.

## Проверка патча

Локальная проверка на тестовом provider transport: **78 passed, 2 skipped, 361 subtests passed**. Это подтверждает поведение кода и тестов; реальный запрос к внешнему Hubris endpoint в этой среде не выполнялся, поэтому успешность live-вызова после установки ещё нужно проверить у себя.

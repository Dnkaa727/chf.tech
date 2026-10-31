# Патч: точные доказательства для `confidently_incorrect`

## Что исправлено

Предыдущий live-ответ показал, что модель иногда добавляет в `confidently_incorrect.evidence_ids` как ложное утверждение, так и правильную предпосылку рядом с ним.

Теперь Stage 2 получает более точную инструкцию: если среди выбранных доказательств есть сегменты, которым оценка критерия присвоила отношение `contradicts`, для `confidently_incorrect` следует оставить только такие сегменты. Правильные (`supports`), частично подтверждающие и нейтральные соседние фрагменты не должны становиться доказательствами ложного утверждения.

В Python добавлена дополнительная детерминированная защита: если модель всё же передаст смешанный список, в котором есть и `supports`, и `contradicts`, итоговый `confidently_incorrect.evidence` будет собран только из сегментов `contradicts`.

`technical_contradiction` не фильтруется: он сохраняет обе стороны противоречия. Старое поле `quote` остаётся и содержит первую цитату после фильтрации. Все цитаты по-прежнему берутся из проверенных сегментов ответа кандидата.

Если среди сегментов, выбранных моделью для `confidently_incorrect`, нет ни одного отношения `contradicts`, Python сохраняет список без изменения: это не позволяет автоматически удалить доказательство только из-за отсутствия связи с критерием.

## Файлы

- `v3/engine.py` — более точная инструкция Stage 2 и Python-фильтр доказательств для `confidently_incorrect`.
- `tests/test_v3_red_flag_evidence.py` — два дополнительных теста для смешанного списка доказательств и текста инструкции.

## Установка

Распакуйте архив в корень `D:\RAG_BACKEND_ALL_25` с заменой `v3/engine.py` и `tests/test_v3_red_flag_evidence.py`.

## Проверка

Сначала:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_red_flag_evidence.py -q
```

Затем полный регрессионный набор:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_two_stage.py tests/test_v3_registry.py tests/test_v3_all25.py tests/test_logic.py tests/test_v3_red_flag_checklist.py tests/test_v3_red_flag_evidence.py tests/test_v3_resolution_guard.py -q
```

## Ожидаемое поведение для противоречивого ответа

| Флаг | ID доказательств |
|---|---|
| `confidently_incorrect` | Только сегмент с ложным утверждением, например `S003` |
| `technical_contradiction` | Обе несовместимые части, например `S001` и `S003` |

Число вызовов LLM, схема `red_flag_checks`, начисление баллов, `error_updates` и `resolutions` не меняются.

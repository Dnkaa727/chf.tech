# Патч `segment_assessments`

Патч рассчитан на проект с уже установленным двухэтапным конвейером v3. Он заменяет формат группировки доказательств только на втором этапе.

## Что меняется

Раньше Stage 2 возвращал четыре независимых массива ID (`supporting_segment_ids`, `partially_supporting_segment_ids`, `contradicting_segment_ids`, `neutral_segment_ids`). Теперь для каждого критерия он возвращает один объект `segment_assessments`, где каждый связанный `segment_id` — обязательный ключ с одним значением: `supports`, `partially_supports`, `contradicts` или `neutral`.

JSON Schema динамически строится Python для каждого критерия: обязательны все связанные ID, неизвестные ключи запрещены, значение ограничено четырьмя категориями. `reviewed_segment_ids` также становится объектом с фиксированными ключами, чтобы не допускать пропусков или повторов в глобальном списке просмотра. Python затем формирует привычные внутренние записи `evidence`. Внешний ответ `/v3/evaluate` не меняется.

## Установка

1. Остановите сервер Uvicorn (`Ctrl+C`).
2. Сделайте резервную копию проекта или файлов, которые будут заменены.
3. Распакуйте ZIP поверх корня проекта, сохранив структуру папок. Патч заменяет только:
   - `v3/engine.py`
   - `v3/diagnostics.py`
   - `tests/test_v3_two_stage.py`
   - `docs/TWO_STAGE_PIPELINE_RU.md`
4. Не меняйте `.env`, `.venv` или API-ключ. `LLM_PIPELINE_MODE=two_stage` остаётся основным режимом.

## Проверка без обращения к LLM

Из PowerShell в корне проекта выполните:

```powershell
python -m unittest discover -s tests -p "test_v3_two_stage.py" -v
python -m unittest discover -s tests -v
python run.py check
python logic_probes_24.py --card PY-ASYNC-01 --compare
```

Ожидаемый результат на подготовленном снимке: `157 tests ... OK (skipped=4)`, 25 карточек, 25 рубрик, 150 eval cases, 50 red-team cases. Offline-пробы должны вывести `OFFLINE` и не обращаться к модели.

## Реальная проверка

После успешных офлайн-тестов можно выполнить один платный тест:

```powershell
python logic_probes_24.py --card PY-ASYNC-01 --case C_plain_reasoning --live
```

Для теста используются два вызова LLM: сегментация и оценка. Сначала проверьте один сценарий; `--compare --live --confirm-cost` запускает несколько платных сценариев. Сверьте баллы и evidence с экспертом. Unit-тесты проверяют структуру и целостность, но не доказывают семантическую точность модели.

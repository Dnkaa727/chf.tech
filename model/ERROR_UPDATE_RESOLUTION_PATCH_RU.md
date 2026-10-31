# Patch: безопасная обработка `error_updates` и `resolutions`

## Что исправлено

В Stage 2 модель иногда возвращает `resolutions` с `error_id: ""` или с ID, которого нет среди открытых ошибок сессии. Раньше такой элемент приводил к `invalid_error_link` и отклонению всего ответа (`502`), хотя сами баллы и red flags могли быть корректными.

Теперь:

1. Инструкция Stage 2 явно требует `resolutions: []`, если в `evaluation_state` нет открытых ошибок.
2. Если открытые ошибки есть, модель получает их ID в инструкции и должна использовать только один из них.
3. Python пропускает попытки закрыть пустой, неизвестный или уже закрытый `error_id`. Такая попытка не закрывает ошибку и не отменяет оценку кандидата.
4. Корректные resolution с существующим открытым `error_id` по-прежнему проходят полную проверку: criterion, evidence, положительная оценка и отсутствие конфликта с новой ошибкой.
5. Логика `error_updates` остаётся строгой. Для обнаруженного существенного флага Python создаёт безопасную запись по умолчанию, если модель не вернула `error_update`.

## Установка

Распаковать архив в корень проекта `D:\RAG_BACKEND_ALL_25` с заменой `v3/engine.py` и добавлением `tests/test_v3_resolution_guard.py`.

Патч рассчитан на версию проекта после установки `RAG_BACKEND_ALL_25_RED_FLAG_EVIDENCE_PATCH.zip`.

## Проверка

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_resolution_guard.py -q
```

Затем полный набор из предыдущих прогонов:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_v3_two_stage.py tests/test_v3_registry.py tests/test_v3_all25.py tests/test_logic.py tests/test_v3_red_flag_checklist.py tests/test_v3_red_flag_evidence.py tests/test_v3_resolution_guard.py -q
```

Новые тесты покрывают: игнорирование пустого `error_id` без потери оценки, приём допустимого ID открытой ошибки и обязательную пустоту `resolutions`, когда открытых ошибок нет.

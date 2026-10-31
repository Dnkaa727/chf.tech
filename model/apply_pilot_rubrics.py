#!/usr/bin/env python3
"""Apply the three-card rubric wording pilot without changing the rubric schema.

Run from the project root:
    python apply_pilot_rubrics.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "pilot_rubric_changes.json"
PILOT_NOTE = (
    "Пилотная редакция 3.1: уточнены формулировки вопросов, критериев и якорей. "
    "Оценивается технический смысл и применимость; эквивалентные корректные решения "
    "засчитываются без требования буквального совпадения с конкретным API или термином. "
    "Экспертная валидация ещё не проведена."
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def render_json(value) -> bytes:
    # Preserve the project's existing UTF-8 / indent=2 / no-final-newline convention.
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def backup(path: Path, stamp: str) -> Path | None:
    if not path.exists():
        return None
    backup_path = path.with_name(path.name + ".before_pilot_" + stamp + ".bak")
    shutil.copy2(path, backup_path)
    return backup_path


def main() -> int:
    root = Path.cwd()
    rubric_path = root / "data" / "rubrics_all_25.json"
    kb_path = root / "data" / "knowledge_base.json"
    test_path = root / "tests" / "test_v3_registry.py"

    missing = [str(p.relative_to(root)) for p in (rubric_path, kb_path) if not p.is_file()]
    if missing:
        raise SystemExit(
            "Не найдены файлы проекта: " + ", ".join(missing) +
            ". Запусти скрипт из корневой папки RAG_BACKEND_ALL_25."
        )

    manifest = read_json(MANIFEST)
    original_rubric_bytes = rubric_path.read_bytes()
    original_rubric_sha = hashlib.sha256(original_rubric_bytes).hexdigest()
    rubric_data = json.loads(original_rubric_bytes.decode("utf-8"))
    kb_data = read_json(kb_path)
    if rubric_data.get("schema_version") != "3.0" or kb_data.get("schema_version") != "2.0":
        raise SystemExit("Неожиданная версия JSON-схемы. Файлы не изменены.")

    rubric_rows = rubric_data.get("rubrics")
    kb_rows = kb_data.get("cards")
    if not isinstance(rubric_rows, list) or not isinstance(kb_rows, list):
        raise SystemExit("Некорректная структура каталогов. Файлы не изменены.")

    rubric_index = {}
    for row in rubric_rows:
        rubric_index.setdefault(row.get("card_id"), []).append(row)
    kb_index = {}
    for row in kb_rows:
        kb_index.setdefault(row.get("id"), []).append(row)

    updates = manifest["cards"]
    for card_id, change in updates.items():
        if len(rubric_index.get(card_id, [])) != 1 or len(kb_index.get(card_id, [])) != 1:
            raise SystemExit(f"Карточка {card_id}: ожидается ровно одна запись в обоих JSON. Файлы не изменены.")
        rubric = rubric_index[card_id][0]
        card = kb_index[card_id][0]
        criteria = rubric.get("criteria")
        if not isinstance(criteria, list) or len(criteria) != 5:
            raise SystemExit(f"Карточка {card_id}: ожидалось ровно пять критериев. Файлы не изменены.")
        criterion_index = {}
        for criterion in criteria:
            criterion_index.setdefault(criterion.get("id"), []).append(criterion)
        if set(criterion_index) != set(change["criteria"]) or any(len(v) != 1 for v in criterion_index.values()):
            raise SystemExit(f"Карточка {card_id}: набор ID критериев отличается от манифеста. Файлы не изменены.")

    for card_id, change in updates.items():
        rubric = rubric_index[card_id][0]
        card = kb_index[card_id][0]
        rubric["question"] = change["question"]
        card["question"] = change["question"]
        rubric["version"] = manifest["pilot_version"]
        note = rubric.get("review_note", "").strip()
        if PILOT_NOTE not in note:
            rubric["review_note"] = (note + " " + PILOT_NOTE).strip()
        for criterion_id, criterion_change in change["criteria"].items():
            criterion = next(c for c in rubric["criteria"] if c["id"] == criterion_id)
            criterion["name"] = criterion_change["name"]
            criterion["anchors"] = criterion_change["anchors"]
            criterion["followup_question"] = criterion_change["followup_question"]

    rubric_bytes = render_json(rubric_data)
    kb_bytes = render_json(kb_data)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    changed_paths = []
    if rubric_bytes != rubric_path.read_bytes():
        backup(rubric_path, stamp)
        atomic_write(rubric_path, rubric_bytes)
        changed_paths.append(rubric_path)
    if kb_bytes != kb_path.read_bytes():
        backup(kb_path, stamp)
        atomic_write(kb_path, kb_bytes)
        changed_paths.append(kb_path)

    # Keep the repository's historical rubric checksum test aligned with the intentional pilot.
    if test_path.is_file():
        test_text = test_path.read_text(encoding="utf-8")
        if original_rubric_sha in test_text:
            new_sha = hashlib.sha256(rubric_bytes).hexdigest()
            updated_test = test_text.replace(original_rubric_sha, new_sha)
            updated_test = updated_test.replace(
                "test_all_125_rubric_criteria_and_file_content_stay_unchanged",
                "test_all_125_rubric_criteria_and_pilot_baseline"
            )
            if updated_test != test_text:
                backup(test_path, stamp)
                atomic_write(test_path, updated_test.encode("utf-8"))
                changed_paths.append(test_path)

    # Confirm registry-facing metadata and preserve the original JSON schema shape.
    rubric_check = read_json(rubric_path)
    kb_check = read_json(kb_path)
    for card_id in updates:
        rr = next(x for x in rubric_check["rubrics"] if x["card_id"] == card_id)
        kk = next(x for x in kb_check["cards"] if x["id"] == card_id)
        if rr["question"] != kk["question"] or rr["version"] != manifest["pilot_version"]:
            raise SystemExit(f"Проверка синхронизации не пройдена для {card_id}.")
        if len(rr["criteria"]) != 5 or any(set(c["anchors"]) != {"0", "1", "2"} for c in rr["criteria"]):
            raise SystemExit(f"Проверка якорей не пройдена для {card_id}.")
        if any("details" in c for c in rr["criteria"]):
            raise SystemExit(f"В {card_id} неожиданно появилось поле details.")

    print("Пилот применён:")
    for card_id in updates:
        print(f"  - {card_id}: {manifest['pilot_version']}, 5 критериев, 15 якорей обновлены")
    if changed_paths:
        print("Изменены файлы:")
        for path in changed_paths:
            print("  -", path.relative_to(root))
        print("Резервные копии исходных файлов созданы рядом с ними (*.before_pilot_*.bak).")
    else:
        print("Изменений нет: пилот уже применён.")
    print("Новых полей в рубриках не добавлено.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

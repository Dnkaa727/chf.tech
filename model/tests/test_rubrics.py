"""Structural regression tests for the three-card rubric wording pilot."""

import json
import unittest
from pathlib import Path

from rag.engine import validate_data
from rag.registry import get_registry

ROOT = Path(__file__).resolve().parents[1]
PILOT_IDS = ("PY-ASYNC-01", "PG-TX-01", "API-VAL-01")


class PilotRubricRewriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rubrics = json.loads(
            (ROOT / "data/rubrics_all_25.json").read_text(encoding="utf-8")
        )
        cls.kb = json.loads(
            (ROOT / "data/knowledge_base.json").read_text(encoding="utf-8")
        )
        cls.registry = get_registry()

    def test_catalog_and_rubric_questions_are_synchronised(self):
        cards = {row["id"]: row for row in self.kb["cards"]}
        rubrics = {row["card_id"]: row for row in self.rubrics["rubrics"]}
        for card_id in PILOT_IDS:
            with self.subTest(card_id=card_id):
                self.assertEqual(
                    cards[card_id]["question"], rubrics[card_id]["question"]
                )
                self.assertEqual(rubrics[card_id]["version"], "3.1-pilot")
                self.assertEqual(self.registry.get(card_id).rubric_version, "3.1-pilot")

    def test_five_criteria_and_0_1_2_anchors_are_preserved(self):
        rubrics = {row["card_id"]: row for row in self.rubrics["rubrics"]}
        for card_id in PILOT_IDS:
            with self.subTest(card_id=card_id):
                criteria = rubrics[card_id]["criteria"]
                self.assertEqual(len(criteria), 5)
                self.assertTrue(
                    all(set(row["anchors"]) == {"0", "1", "2"} for row in criteria)
                )
                self.assertTrue(
                    all(
                        all(text.strip() for text in row["anchors"].values())
                        for row in criteria
                    )
                )
                self.assertTrue(all("details" not in row for row in criteria))

    def test_registry_exposes_rewritten_questions_and_anchors(self):
        rubrics = {row["card_id"]: row for row in self.rubrics["rubrics"]}
        for card_id in PILOT_IDS:
            with self.subTest(card_id=card_id):
                rubric = rubrics[card_id]
                loaded = self.registry.get(card_id).rubric
                self.assertEqual(loaded["question"], rubric["question"])
                loaded_criteria = {row["id"]: row for row in loaded["criteria"]}
                for criterion in rubric["criteria"]:
                    self.assertEqual(
                        loaded_criteria[criterion["id"]]["name"], criterion["name"]
                    )
                    self.assertEqual(
                        loaded_criteria[criterion["id"]]["anchors"],
                        criterion["anchors"],
                    )

    def test_full_catalog_still_validates(self):
        result = validate_data()
        self.assertEqual(result["cards"], 25)
        self.assertEqual(result["criteria"], 125)


if __name__ == "__main__":
    unittest.main()

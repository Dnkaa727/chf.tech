"""Состояние интервью: в памяти Python (для демо), без хранения персональных данных."""
from dataclasses import dataclass, field
from .core import read_data, CRITERIA_IDS, decide_next, merge_evidence


@dataclass
class InterviewSession:
    """Не меняем общую базу знаний. Память отдельная на каждую сессию."""
    topic_id: str = "pg_slow_query"
    followups_asked: int = 0
    asked_targets: list[str] = field(default_factory=list)
    criterion_evidence: dict = field(default_factory=lambda: {c: {"points": 0, "quote": ""} for c in CRITERIA_IDS})
    transcript: list[dict] = field(default_factory=list)
    pending_question: str = ""
    status: str = "in_progress"

    def __post_init__(self):
        if not self.pending_question:
            self.pending_question = read_data("rubric_postgresql.json")["question"]

    def record_answer(self, answer: str, evaluation: dict) -> dict:
        if self.status != "in_progress":
            raise ValueError("Session already ended this topic")
        # LLM оценки уже должны пройти verify_model_output().
        before = dict(self.criterion_evidence)
        self.criterion_evidence = merge_evidence(self.criterion_evidence, evaluation["criteria"])
        aggregated = dict(evaluation)
        aggregated["criteria"] = self.criterion_evidence
        aggregated["score"] = sum(v["points"] for v in self.criterion_evidence.values())
        # Если в новом ответе есть серьёзное противоречие, нельзя «выключить» его более ранними плюсами.
        if "technical_contradiction" in evaluation.get("red_flags", []) and aggregated["score"] >= 7:
            aggregated["uncertainty"] = "high"
        decision = decide_next(aggregated, {
            "followups_asked": self.followups_asked,
            "asked_targets": self.asked_targets,
        })
        self.transcript.append({
            "question": self.pending_question,
            "answer": answer,
            "assessment": evaluation,
            "cumulative_score": aggregated["score"],
            "decision": decision,
        })
        if decision["action"] == "followup":
            self.followups_asked += 1
            self.asked_targets.append(decision["target"])
            self.pending_question = decision["question"]
        else:
            self.status = decision["action"]
            self.pending_question = ""
        return decision

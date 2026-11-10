"""logic_manager_ai_assessment.py - an assessment produced by the AI model."""

from logic_manager_assessment import Assessment


class AIAssessment(Assessment):
    """The AI model's structured view of one error log."""

    CONFIDENCE_MIN = 0.0
    CONFIDENCE_MAX = 1.0

    def __init__(self, machine_subsystem: str, severity: int,
                 root_cause_hypothesis: str, patient_safety_risk: bool,
                 recurrence_indicator: bool, recommended_action: str,
                 confidence: float) -> None:
        super().__init__(severity, patient_safety_risk, recurrence_indicator)
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not self.CONFIDENCE_MIN <= confidence <= self.CONFIDENCE_MAX):
            raise ValueError(f"confidence must be a number 0-1, got {confidence!r}")
        self._confidence: float = confidence
        self._machine_subsystem: str = machine_subsystem
        self._root_cause_hypothesis: str = root_cause_hypothesis
        self._recommended_action: str = recommended_action

    @property
    def machine_subsystem(self) -> str:
        return self._machine_subsystem

    @property
    def root_cause_hypothesis(self) -> str:
        return self._root_cause_hypothesis

    @property
    def recommended_action(self) -> str:
        return self._recommended_action

    def confidence(self) -> float:
        return self._confidence

    def source(self) -> str:
        return "ai"

    def to_dict(self) -> dict:
        return {
            "machine_subsystem": self._machine_subsystem,
            "severity": self._severity,
            "root_cause_hypothesis": self._root_cause_hypothesis,
            "patient_safety_risk": self._patient_safety_risk,
            "recurrence_indicator": self._recurrence_indicator,
            "recommended_action": self._recommended_action,
            "confidence": self._confidence,
        }

    @staticmethod
    def from_dict(data: dict) -> "AIAssessment":
        """Rebuild from stored JSON. Raises ValueError if the data is invalid."""
        if not isinstance(data, dict):
            raise ValueError("AI assessment must be a dictionary")
        return AIAssessment(
            machine_subsystem=data.get("machine_subsystem", ""),
            severity=data.get("severity"),
            root_cause_hypothesis=data.get("root_cause_hypothesis", ""),
            patient_safety_risk=data.get("patient_safety_risk"),
            recurrence_indicator=data.get("recurrence_indicator"),
            recommended_action=data.get("recommended_action", ""),
            confidence=data.get("confidence"),
        )

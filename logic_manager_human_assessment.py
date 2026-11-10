"""logic_manager_human_assessment.py - an assessment approved by a reviewer."""

from logic_manager_assessment import Assessment


class HumanAssessment(Assessment):
    """A reviewer's verdict; it overrides the AI result and is fully trusted."""

    def __init__(self, severity: int, patient_safety_risk: bool,
                 recurrence_indicator: bool, assessment_source: str,
                 reviewed_at: str) -> None:
        super().__init__(severity, patient_safety_risk, recurrence_indicator)
        self._assessment_source: str = assessment_source
        self._reviewed_at: str = reviewed_at

    @property
    def assessment_source(self) -> str:
        return self._assessment_source

    @property
    def reviewed_at(self) -> str:
        return self._reviewed_at

    def confidence(self) -> float:
        return 1.0

    def source(self) -> str:
        return self._assessment_source

    def to_dict(self) -> dict:
        # "recurrence_indicator" is not stored: it always comes from the AI.
        return {
            "status": "approved",
            "severity": self._severity,
            "patient_safety_risk": self._patient_safety_risk,
            "assessment_source": self._assessment_source,
            "reviewed_at": self._reviewed_at,
        }

    @staticmethod
    def from_dict(data: dict, recurrence_indicator: bool) -> "HumanAssessment":
        """Rebuild from stored JSON. Raises ValueError if the data is invalid."""
        if not isinstance(data, dict) or data.get("status") != "approved":
            raise ValueError("human review is not an approved assessment")
        return HumanAssessment(
            severity=data.get("severity"),
            patient_safety_risk=data.get("patient_safety_risk"),
            recurrence_indicator=recurrence_indicator,
            assessment_source=data.get("assessment_source", ""),
            reviewed_at=data.get("reviewed_at", ""),
        )

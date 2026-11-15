"""logic_manager_assessment.py - abstract base for every fault assessment."""

from abc import ABC, abstractmethod


class Assessment(ABC):
    """A severity judgement about one error log.

    Abstract class: the triage rules only ever talk to an Assessment, so an
    AI result and a human review can be used interchangeably (LSP).
    """

    SEVERITY_MIN = 1
    SEVERITY_MAX = 5

    def __init__(self, severity: int, patient_safety_risk: bool,
                 recurrence_indicator: bool) -> None:
        # Encapsulation: an Assessment can never hold an invalid severity.
        if (isinstance(severity, bool) or not isinstance(severity, int)
                or not self.SEVERITY_MIN <= severity <= self.SEVERITY_MAX):
            raise ValueError(f"severity must be an integer 1-5, got {severity!r}")
        if not isinstance(patient_safety_risk, bool):
            raise ValueError("patient_safety_risk must be a boolean")
        if not isinstance(recurrence_indicator, bool):
            raise ValueError("recurrence_indicator must be a boolean")
        self._severity: int = severity
        self._patient_safety_risk: bool = patient_safety_risk
        self._recurrence_indicator: bool = recurrence_indicator

    @property
    def severity(self) -> int:
        return self._severity

    @property
    def patient_safety_risk(self) -> bool:
        return self._patient_safety_risk

    @property
    def recurrence_indicator(self) -> bool:
        return self._recurrence_indicator

    @abstractmethod
    def confidence(self) -> float:
        """How certain this assessment is, from 0.0 to 1.0."""

    @abstractmethod
    def source(self) -> str:
        """Who produced the assessment."""

    @abstractmethod
    def to_dict(self) -> dict:
        """Serialise in the JSON format used by processed_records.json."""

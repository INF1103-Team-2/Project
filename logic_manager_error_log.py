"""logic_manager_error_log.py - one machine error log (replaces the old record dict)."""

import hashlib
import logging
import re
from datetime import datetime
from typing import Optional

from logic_manager_ai_assessment import AIAssessment
from logic_manager_assessment import Assessment
from logic_manager_decision import Decision
from logic_manager_human_assessment import HumanAssessment

logger = logging.getLogger(__name__)


class ErrorLog:
    """A single error reported by a hospital machine, plus everything learnt about it."""

    # Validation rules shared by ConsoleUI and LogFileReader.
    MACHINE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{2,19}$")
    ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{1,19}$")
    MACHINE_TYPES = ("CT scanner", "X-ray machine")
    MIN_MESSAGE_LENGTH = 10
    MAX_MESSAGE_LENGTH = 500
    TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

    def __init__(self, machine_id: str, error_code: str, machine_type: str,
                 timestamp: str, reported_by: str, raw_message: str,
                 log_id: Optional[str] = None) -> None:
        self._log_id: str = log_id or ErrorLog.make_log_id(machine_id, timestamp, raw_message)
        self._machine_id: str = machine_id
        self._error_code: str = error_code
        self._machine_type: str = machine_type
        self._timestamp: str = timestamp
        self._reported_by: str = reported_by
        self._raw_message: str = raw_message
        self._ai_assessment: Optional[AIAssessment] = None
        self._ai_error: Optional[str] = None
        self._human_assessment: Optional[HumanAssessment] = None
        self._decision: Optional[Decision] = None

    # ----- read-only properties -------------------------------------------
    @property
    def log_id(self) -> str:
        return self._log_id

    @property
    def machine_id(self) -> str:
        return self._machine_id

    @property
    def error_code(self) -> str:
        return self._error_code

    @property
    def machine_type(self) -> str:
        return self._machine_type

    @property
    def timestamp(self) -> str:
        return self._timestamp

    @property
    def reported_by(self) -> str:
        return self._reported_by

    @property
    def raw_message(self) -> str:
        return self._raw_message

    @property
    def ai_assessment(self) -> Optional[AIAssessment]:
        return self._ai_assessment

    @property
    def ai_error(self) -> Optional[str]:
        return self._ai_error

    @property
    def human_assessment(self) -> Optional[HumanAssessment]:
        return self._human_assessment

    @property
    def decision(self) -> Optional[Decision]:
        return self._decision

    # ----- AI result (association: AIClient builds the AIAssessment) -------
    def set_ai_assessment(self, assessment: AIAssessment) -> None:
        self._ai_assessment = assessment
        self._ai_error = None

    def set_ai_error(self, message: str) -> None:
        self._ai_assessment = None
        self._ai_error = message

    # ----- human review (composition: this object creates the assessment) --
    def record_human_review(self, severity: int, safety_risk: bool, source: str) -> None:
        """Store a reviewer's verdict. It overrides the AI result from now on."""
        recurring = self._ai_assessment.recurrence_indicator if self._ai_assessment else False
        self._human_assessment = HumanAssessment(
            severity=severity,
            patient_safety_risk=safety_risk,
            recurrence_indicator=recurring,
            assessment_source=source,
            reviewed_at=datetime.now().strftime(self.TIME_FORMAT),
        )

    def effective_assessment(self) -> Optional[Assessment]:
        """The assessment the rules should use: a human review beats the AI."""
        if self._human_assessment is not None:
            return self._human_assessment
        return self._ai_assessment

    # ----- decision (composition) ------------------------------------------
    def apply_decision(self, route: str, score: int, notify_now: bool, send_time: str,
                       requires_review: bool, rules_fired: list[str]) -> None:
        """Create a fresh Decision for this log, replacing any earlier one."""
        self._decision = Decision(route, score, notify_now, send_time,
                                  requires_review, rules_fired)

    # ----- JSON -------------------------------------------------------------
    def to_dict(self) -> dict:
        data = {
            "log_id": self._log_id,
            "machine_id": self._machine_id,
            "error_code": self._error_code,
            "machine_type": self._machine_type,
            "timestamp": self._timestamp,
            "reported_by": self._reported_by,
            "raw_message": self._raw_message,
            "ai": self._ai_assessment.to_dict() if self._ai_assessment else None,
        }
        if self._ai_error is not None:
            data["ai_error"] = self._ai_error
        if self._decision is not None:
            data["decision"] = self._decision.to_dict()
        if self._human_assessment is not None:
            data["human_review"] = self._human_assessment.to_dict()
        return data

    @staticmethod
    def from_dict(data: dict) -> "ErrorLog":
        """Rebuild an ErrorLog from processed_records.json."""
        log = ErrorLog(
            machine_id=data.get("machine_id", ""),
            error_code=data.get("error_code", ""),
            machine_type=data.get("machine_type", ""),
            timestamp=data.get("timestamp", ""),
            reported_by=data.get("reported_by", ""),
            raw_message=data.get("raw_message", ""),
            log_id=data.get("log_id"),
        )
        if data.get("ai") is not None:
            try:
                log._ai_assessment = AIAssessment.from_dict(data["ai"])
            except ValueError:
                logger.warning("Record %s has an invalid AI assessment", log.log_id)
        log._ai_error = data.get("ai_error")
        if data.get("human_review") is not None:
            recurring = log._ai_assessment.recurrence_indicator if log._ai_assessment else False
            try:
                log._human_assessment = HumanAssessment.from_dict(data["human_review"], recurring)
            except ValueError:
                logger.warning("Record %s has an invalid human assessment", log.log_id)
        if isinstance(data.get("decision"), dict):
            log._decision = Decision.from_dict(data["decision"])
        return log

    # ----- shared helpers ---------------------------------------------------
    @staticmethod
    def make_log_id(machine_id: str, timestamp: str, raw_message: str) -> str:
        """Same input always gives the same id, so re-uploads are de-duplicated."""
        payload = f"{machine_id}|{timestamp}|{raw_message}".encode("utf-8")
        return hashlib.sha1(payload).hexdigest()[:12]

    @staticmethod
    def parse_timestamp(value: str) -> Optional[str]:
        """Validate a timestamp and return it as YYYY-MM-DDTHH:MM:SS, else None."""
        cleaned = value.replace("Z", "").strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(cleaned, fmt).strftime(ErrorLog.TIME_FORMAT)
            except ValueError:
                continue
        return None

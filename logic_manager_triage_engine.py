"""logic_manager_triage_engine.py - business rules R0-R6, scoring and send times."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from logic_manager_assessment import Assessment
from logic_manager_error_log import ErrorLog

logger = logging.getLogger(__name__)


class TriageEngine:
    """Decides the route, priority score and alert time for each ErrorLog."""

    # Scoring weights (0-100 scale)
    SEVERITY_WEIGHT = 14
    SAFETY_RISK_BONUS = 20
    RECURRENCE_BONUS = 10
    LOW_CONFIDENCE_PENALTY = 15

    # Rule thresholds
    HIGH_SEVERITY = 4
    MODERATE_SEVERITY = 3
    LOW_SEVERITY = 2
    CONFIDENT = 0.70          # Business Rule 5: below 70% -> PENDING REVIEW
    LOW_CONFIDENCE = 0.5

    # Routes
    ROUTE_IMMEDIATE = "immediate_escalation"
    ROUTE_HUMAN_TRIAGE = "human_triage"
    ROUTE_RECURRING = "recurring_fault_review"
    ROUTE_STANDARD = "standard_queue"
    ROUTE_SCHEDULED = "scheduled_maintenance"
    ROUTE_AI_UNAVAILABLE = "ai_unavailable_manual_review"

    ALERT_HOUR = 7

    def __init__(self) -> None:
        self._defer_days_by_route: dict[str, int] = {
            self.ROUTE_IMMEDIATE: 0,
            self.ROUTE_HUMAN_TRIAGE: 0,
            self.ROUTE_AI_UNAVAILABLE: 0,
            self.ROUTE_RECURRING: 1,
            self.ROUTE_STANDARD: 2,
            self.ROUTE_SCHEDULED: 5,
        }

    def evaluate(self, log: ErrorLog, now: Optional[datetime] = None) -> None:
        """Run every rule against the log and attach a new Decision to it."""
        if now is None:
            now = datetime.now()

        # Polymorphism: works the same for an AIAssessment or a HumanAssessment.
        assessment = log.effective_assessment()
        route = self._route(assessment)
        score = self._score(assessment)
        defer_days = self._defer_days_by_route.get(route, 2)
        notify_now = defer_days == 0

        log.apply_decision(
            route=route,
            score=score,
            notify_now=notify_now,
            send_time=(now.strftime(ErrorLog.TIME_FORMAT) if notify_now
                       else self._next_alert_time(now, defer_days)),
            requires_review=route in (self.ROUTE_HUMAN_TRIAGE, self.ROUTE_AI_UNAVAILABLE),
            rules_fired=self._rules_fired(log),
        )
        logger.info("Record %s routed to %s with score %d", log.log_id, route, score)

    def _score(self, assessment: Optional[Assessment]) -> int:
        """0-100 priority; 0 when there is no usable assessment."""
        if assessment is None:
            return 0
        total = assessment.severity * self.SEVERITY_WEIGHT
        if assessment.patient_safety_risk:
            total += self.SAFETY_RISK_BONUS
        if assessment.recurrence_indicator:
            total += self.RECURRENCE_BONUS
        if assessment.confidence() < self.LOW_CONFIDENCE:
            total -= self.LOW_CONFIDENCE_PENALTY
        return max(0, min(100, total))

    def _route(self, assessment: Optional[Assessment]) -> str:
        """Rules in priority order; the first match wins (R1 > R2 > R3 > R4)."""
        if assessment is None:
            return self.ROUTE_AI_UNAVAILABLE
        severity = assessment.severity
        confidence = assessment.confidence()
        if (severity >= self.HIGH_SEVERITY and assessment.patient_safety_risk
                and confidence >= self.CONFIDENT):
            return self.ROUTE_IMMEDIATE
        if confidence < self.CONFIDENT:
            return self.ROUTE_HUMAN_TRIAGE
        if assessment.recurrence_indicator and severity >= self.MODERATE_SEVERITY:
            return self.ROUTE_RECURRING
        if severity <= self.LOW_SEVERITY and not assessment.patient_safety_risk:
            return self.ROUTE_SCHEDULED
        return self.ROUTE_STANDARD

    def _rules_fired(self, log: ErrorLog) -> list[str]:
        """Every named rule that applied, for the audit trail."""
        assessment = log.effective_assessment()
        if assessment is None:
            return ["R0_ai_unavailable"]
        severity = assessment.severity
        confidence = assessment.confidence()
        safety_risk = assessment.patient_safety_risk

        fired = []
        if log.human_assessment is not None:
            fired.append("R6_human_assessment_approved")
        if severity >= self.HIGH_SEVERITY and safety_risk and confidence >= self.CONFIDENT:
            fired.append("R1_confident_high_severity_safety_risk")
        if confidence < self.CONFIDENT:
            fired.append("R2_low_confidence_pending_review")
        if assessment.recurrence_indicator and severity >= self.MODERATE_SEVERITY:
            fired.append("R3_recurring_moderate_or_worse")
        if severity <= self.LOW_SEVERITY and not safety_risk:
            fired.append("R4_low_severity_no_safety_risk")
        if confidence < self.LOW_CONFIDENCE:
            fired.append("R5_confidence_penalty_applied")
        return fired

    def _next_alert_time(self, now: datetime, defer_days: int) -> str:
        """Deferred alerts land at 07:00 on the target day, never overnight."""
        target = (now + timedelta(days=defer_days)).replace(
            hour=self.ALERT_HOUR, minute=0, second=0, microsecond=0
        )
        if target <= now:
            target = target + timedelta(days=1)
        return target.strftime(ErrorLog.TIME_FORMAT)

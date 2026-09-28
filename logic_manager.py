import logging
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SEVERITY_WEIGHT = 14
SAFETY_RISK_BONUS = 20
RECURRENCE_BONUS = 10
LOW_CONFIDENCE_PENALTY = 15

HIGH_SEVERITY = 4
MODERATE_SEVERITY = 3
LOW_SEVERITY = 2
CONFIDENT = 0.7
LOW_CONFIDENCE = 0.5

ROUTE_IMMEDIATE = "immediate_escalation"
ROUTE_HUMAN_TRIAGE = "human_triage"
ROUTE_RECURRING = "recurring_fault_review"
ROUTE_STANDARD = "standard_queue"
ROUTE_SCHEDULED = "scheduled_maintenance"
ROUTE_AI_UNAVAILABLE = "ai_unavailable_manual_review"

DEFER_DAYS_BY_ROUTE = {
    ROUTE_IMMEDIATE: 0,
    ROUTE_HUMAN_TRIAGE: 0,
    ROUTE_AI_UNAVAILABLE: 0,
    ROUTE_RECURRING: 1,
    ROUTE_STANDARD: 2,
    ROUTE_SCHEDULED: 5,
}
ALERT_HOUR = 7

def score(record: dict) -> int:
    """Produce a 0-100 priority score from the AI output fields."""
    ai = record.get("ai")
    if not ai:
        return 0
    severity = int(ai.get("severity", 1))
    confidence = float(ai.get("confidence", 0.0))
    total = severity * SEVERITY_WEIGHT
    if ai.get("patient_safety_risk"):
        total += SAFETY_RISK_BONUS
    if ai.get("recurrence_indicator"):
        total += RECURRENCE_BONUS
    if confidence < LOW_CONFIDENCE:
        total -= LOW_CONFIDENCE_PENALTY
    return max(0, min(100, total))

def route(record: dict) -> str:
    """Assign the record to an outcome path using the AI assessment."""
    ai = record.get("ai")
    if not ai:
        return ROUTE_AI_UNAVAILABLE
    severity = int(ai.get("severity", 1))
    confidence = float(ai.get("confidence", 0.0))
    safety_risk = bool(ai.get("patient_safety_risk"))
    recurring = bool(ai.get("recurrence_indicator"))
    if severity >= HIGH_SEVERITY and safety_risk and confidence >= CONFIDENT:
        return ROUTE_IMMEDIATE
    if severity >= HIGH_SEVERITY and confidence < CONFIDENT:
        return ROUTE_HUMAN_TRIAGE
    if recurring and severity >= MODERATE_SEVERITY:
        return ROUTE_RECURRING
    if severity <= LOW_SEVERITY and not safety_risk:
        return ROUTE_SCHEDULED
    return ROUTE_STANDARD

def rules_fired(record: dict) -> list:
    """List the named rules that applied, for auditability in the report."""
    ai = record.get("ai")
    if not ai:
        return ["R0_ai_unavailable"]
    severity = int(ai.get("severity", 1))
    confidence = float(ai.get("confidence", 0.0))
    safety_risk = bool(ai.get("patient_safety_risk"))
    recurring = bool(ai.get("recurrence_indicator"))
    fired = []
    if severity >= HIGH_SEVERITY and safety_risk and confidence >= CONFIDENT:
        fired.append("R1_confident_high_severity_safety_risk")
    if severity >= HIGH_SEVERITY and confidence < CONFIDENT:
        fired.append("R2_high_severity_low_confidence")
    if recurring and severity >= MODERATE_SEVERITY:
        fired.append("R3_recurring_moderate_or_worse")
    if severity <= LOW_SEVERITY and not safety_risk:
        fired.append("R4_low_severity_no_safety_risk")
    if confidence < LOW_CONFIDENCE:
        fired.append("R5_confidence_penalty_applied")
    return fired

def next_alert_time(now: datetime, defer_days: int) -> str:
    """Return the ISO timestamp at which a deferred alert should be sent."""
    target = (now + timedelta(days=defer_days)).replace(
        hour=ALERT_HOUR, minute=0, second=0, microsecond=0
    )
    if target <= now:
        target = target + timedelta(days=1)
    return target.strftime("%Y-%m-%dT%H:%M:%S")

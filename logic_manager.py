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

"""logic_manager.py - Logic layer (INF1103 Phase 1).

The domain brain. Every business rule for biomedical equipment triage lives
here, and every rule acts on fields the AI produced.

This module is deliberately pure: no printing, no file access, no network
calls, and 'now' is passed in rather than read from the clock. That is what
makes it testable against hardcoded AI responses with no live API, and what
keeps the scheduling decisions repeatable.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# --- Scoring weights (0-100 scale) -----------------------------------------
SEVERITY_WEIGHT = 14          # severity 1-5  -> up to 70
SAFETY_RISK_BONUS = 20
RECURRENCE_BONUS = 10
LOW_CONFIDENCE_PENALTY = 15

# --- Rule thresholds -------------------------------------------------------
HIGH_SEVERITY = 4
MODERATE_SEVERITY = 3
LOW_SEVERITY = 2
CONFIDENT = 0.7
LOW_CONFIDENCE = 0.5

# --- Routes ----------------------------------------------------------------
ROUTE_IMMEDIATE = "immediate_escalation"
ROUTE_HUMAN_TRIAGE = "human_triage"
ROUTE_RECURRING = "recurring_fault_review"
ROUTE_STANDARD = "standard_queue"
ROUTE_SCHEDULED = "scheduled_maintenance"
ROUTE_AI_UNAVAILABLE = "ai_unavailable_manual_review"

# How long each route waits before the engineer is alerted.
DEFER_DAYS_BY_ROUTE = {
    ROUTE_IMMEDIATE: 0,
    ROUTE_HUMAN_TRIAGE: 0,
    ROUTE_AI_UNAVAILABLE: 0,
    ROUTE_RECURRING: 1,
    ROUTE_STANDARD: 2,
    ROUTE_SCHEDULED: 5,
}

# Deferred alerts are sent at the start of the working day, never overnight.
ALERT_HOUR = 7
REPEAT_OFFENDER_THRESHOLD = 2


# ===========================================================================
# Scoring
# ===========================================================================
def score(record: dict) -> int:
    """Produce a 0-100 priority score from the AI output fields.

    Used for ranking the work queue. Returns 0 when AI enrichment is absent,
    since an unassessed record cannot be ranked against assessed ones.
    """
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


# ===========================================================================
# Routing
# ===========================================================================
def route(record: dict) -> str:
    """Assign the record to an outcome path using the AI assessment.

    Rules are evaluated in priority order; the first match wins.

    R1 (multi-condition): high severity AND a patient safety risk AND the model
       is confident -> escalate immediately.
    R2 (multi-condition): high severity BUT low confidence -> do not auto-page
       an engineer on a guess; send it to a human to triage.
    R3 (multi-condition): a repeating fault at moderate severity or above ->
       recurring fault review, because the repeat pattern matters more than any
       single occurrence.
    R4 (multi-condition): low severity AND no safety risk -> batch it into
       scheduled maintenance.
    """
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


# ===========================================================================
# Alert scheduling
# ===========================================================================
def next_alert_time(now: datetime, defer_days: int) -> str:
    """Return the ISO timestamp at which a deferred alert should be sent.

    Deferred alerts land at ALERT_HOUR on the target day, so engineers are
    never paged overnight for non-urgent faults. Pure function of its inputs,
    which is what keeps the output identical across runs.
    """
    target = (now + timedelta(days=defer_days)).replace(
        hour=ALERT_HOUR, minute=0, second=0, microsecond=0
    )
    if target <= now:
        target = target + timedelta(days=1)
    return target.strftime("%Y-%m-%dT%H:%M:%S")


# ===========================================================================
# Evaluation
# ===========================================================================
def evaluate(record: dict, now: Optional[datetime] = None) -> dict:
    """Run all business rules against the AI-enriched record.

    Returns a decision dict. Deciding whether to alert happens here; actually
    sending the alert is io_manager's job.
    """
    if now is None:
        now = datetime.now()

    assigned_route = route(record)
    priority = score(record)
    defer_days = DEFER_DAYS_BY_ROUTE.get(assigned_route, 2)
    notify_now = defer_days == 0

    decision = {
        "route": assigned_route,
        "score": priority,
        "notify_now": notify_now,
        "scheduled_send_time": now.strftime("%Y-%m-%dT%H:%M:%S") if notify_now
                               else next_alert_time(now, defer_days),
        "requires_human_review": assigned_route in (ROUTE_HUMAN_TRIAGE, ROUTE_AI_UNAVAILABLE),
        "rules_fired": rules_fired(record),
    }

    logger.info("Record %s routed to %s with score %d",
                record.get("log_id"), assigned_route, priority)
    return decision


def process_record(record: dict, now: Optional[datetime] = None) -> dict:
    """Attach a decision to an AI-enriched record and return the copy."""
    processed = dict(record)
    processed["decision"] = evaluate(record, now=now)
    return processed


# ===========================================================================
# Fleet-level reporting
# ===========================================================================
def summarise(records: list) -> dict:
    """Aggregate stored records into the fleet summary report.

    This is the consolidated view the problem statement asks for: not just
    per-log alerts, but which machines keep failing.
    """
    total = len(records)
    if total == 0:
        return {
            "total": 0,
            "safety_risk_count": 0,
            "human_review_count": 0,
            "mean_score": 0,
            "by_route": {},
            "repeat_offenders": [],
        }

    by_route: dict = {}
    machine_counts: dict = {}
    safety_risk_count = 0
    human_review_count = 0
    score_total = 0

    for record in records:
        ai = record.get("ai") or {}
        decision = record.get("decision") or {}

        route_name = decision.get("route", "unrouted")
        by_route[route_name] = by_route.get(route_name, 0) + 1

        machine_id = record.get("machine_id", "unknown")
        machine_counts[machine_id] = machine_counts.get(machine_id, 0) + 1

        if ai.get("patient_safety_risk"):
            safety_risk_count += 1
        if decision.get("requires_human_review"):
            human_review_count += 1
        score_total += int(decision.get("score", 0))

    repeat_offenders = sorted(
        [(machine, count) for machine, count in machine_counts.items()
         if count >= REPEAT_OFFENDER_THRESHOLD],
        key=lambda pair: (-pair[1], pair[0]),
    )

    return {
        "total": total,
        "safety_risk_count": safety_risk_count,
        "human_review_count": human_review_count,
        "mean_score": round(score_total / total, 1),
        "by_route": by_route,
        "repeat_offenders": repeat_offenders,
    }

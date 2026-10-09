import logging

import os
import requests

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
CONFIDENT = 0.75               # Business Rule 5: below this -> PENDING REVIEW
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
    R2: confidence below 75% (any severity) -> PENDING REVIEW; do not auto-page
       an engineer on a guess; send it to a human to triage (Business Rule 5).
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
    if confidence < CONFIDENT:
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
    if confidence < CONFIDENT:
        fired.append("R2_low_confidence_pending_review")
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
# ===========================================================================
# Telegram notifications  (Jia Yi)

TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"
 
 
def send_telegram(text: str) -> tuple:
    """Send one message to the Telegram bot. Returns (ok, info). Never crashes.
 
    The token and chat id come from the .env file, never from the code:
        TELEGRAM_BOT_TOKEN=...
        TELEGRAM_CHAT_ID=...
    If they are missing, nothing is sent (dry run), so tests and Docker still work.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.warning("Telegram not configured - dry run only")
        return False, "DRY RUN (Telegram not configured)"
 
    try:
        response = requests.post(TELEGRAM_URL.format(token=token),
                                 data={"chat_id": chat_id, "text": text},
                                 timeout=10)
        if response.status_code == 200:
            logger.info("Telegram message sent")
            return True, "Sent"
        logger.error("Telegram returned %s: %s", response.status_code, response.text[:200])
        return False, f"Telegram error {response.status_code}"
    except requests.RequestException as error:
        logger.error("Telegram request failed: %s", error)
        return False, "Could not reach Telegram"
 
 
def build_alert_message(record: dict) -> str:
    """Turn one processed record into the Telegram alert text."""
    ai = record.get("ai") or {}
    decision = record.get("decision") or {}
    title = "🚨 URGENT MACHINE ERROR" if decision.get("notify_now") else "📋 MACHINE ERROR"
    return (
        f"{title}\n"
        f"Machine: {record.get('machine_id', '?')} ({record.get('machine_type', '?')})\n"
        f"Time: {record.get('timestamp', '?')}\n"
        f"Severity: {ai.get('severity', '?')}/5  |  Priority: {decision.get('score', '?')}/100\n"
        f"Patient safety risk: {'YES' if ai.get('patient_safety_risk') else 'no'}\n"
        f"Problem: {ai.get('machine_subsystem', 'unknown')}\n"
        f"Likely cause: {ai.get('root_cause_hypothesis', 'unknown')}\n"
        f"Action required: {ai.get('recommended_action', 'Inspect the machine')}\n"
        f"Ref: {record.get('log_id', '?')}"
    )
 
 
def should_send_now(record: dict) -> bool:
    """Rule 1 + Rule 5: send now only if the decision says notify_now,
    it has not been sent yet, and it does NOT need human review
    (low-confidence / AI-failed records must not go to Telegram)."""
    decision = record.get("decision") or {}
    return (bool(decision.get("notify_now"))
            and not decision.get("requires_human_review")
            and not decision.get("notification_sent"))
 
 
def get_due_alerts(records: list, current_time: str) -> list:
    """Rule 2: deferred alerts whose 07:00 send time has arrived and are unsent.
    current_time is a string like '2026-10-08T07:00:00' (passed in, not read
    from the clock, so the result is repeatable)."""
    due = []
    for record in records:
        decision = record.get("decision") or {}
        if decision.get("notify_now") or decision.get("requires_human_review"):
            continue
        if decision.get("notification_sent"):
            continue
        send_time = decision.get("scheduled_send_time", "")
        if send_time and send_time <= current_time:     # same ISO format, so text compare works
            due.append(record)
    return due
 
 
def build_daily_report(due_records: list) -> str:
    """One combined message for all due non-urgent alerts (avoids spam)."""
    lines = [f"📋 DAILY MACHINE REPORT ({len(due_records)} item(s))"]
    for record in due_records:
        ai = record.get("ai") or {}
        decision = record.get("decision") or {}
        lines.append(f"- {record.get('machine_id', '?')} | sev {ai.get('severity', '?')}/5 | "
                     f"{ai.get('machine_subsystem', '?')} | {decision.get('route', '?')}")
    return "\n".join(lines)
 
 
def mark_sent(record: dict) -> dict:
    """Return a copy of the record marked as sent, so it is never sent twice."""
    updated = dict(record)
    updated["decision"] = dict(record.get("decision") or {})
    updated["decision"]["notification_sent"] = True
    return updated
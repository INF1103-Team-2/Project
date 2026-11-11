"""io_manager_telegram_notifier.py - sends alerts and reports to the engineers' Telegram."""

import logging

import requests

from io_manager_notifier import Notifier
from logic_manager_alert_scheduler import AlertScheduler
from logic_manager_error_log import ErrorLog

logger = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    """Implements Notifier for Telegram, plus two Telegram-only messages (ISP)."""

    TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: str, chat_id: str) -> None:
        self._token: str = (token or "").strip()
        self._chat_id: str = (chat_id or "").strip()
        self._url_template: str = self.TELEGRAM_URL

    def is_configured(self) -> bool:
        return bool(self._token and self._chat_id)

    # ----- Notifier interface ---------------------------------------------
    def notify_urgent(self, log: ErrorLog) -> tuple[bool, str]:
        text = self._build_alert_message(log)
        repeats = log.decision.bundled_count if log.decision else None
        if repeats:
            text += (f"\n(Same error occurred {repeats} times within "
                     f"{AlertScheduler.BUNDLE_WINDOW_MINUTES} minutes)")
        ok, info = self._post(text)
        return ok, f"Telegram: {info}"

    # ----- Telegram-only messages -----------------------------------------
    def send_review_request(self, log: ErrorLog) -> tuple[bool, str]:
        return self._post(
            "A record needs human review. Please check the CLI.\n"
            f"Machine: {log.machine_id}\n"
            f"Ref: {log.log_id}"
        )

    def send_daily_report(self, logs: list[ErrorLog]) -> tuple[bool, str]:
        lines = [f"📋 DAILY MACHINE REPORT ({len(logs)} item(s))"]
        for log in logs:
            ai = log.ai_assessment
            route = log.decision.route if log.decision else "?"
            lines.append(
                f"- {log.machine_id} | sev {ai.severity if ai else '?'}/5 | "
                f"{ai.machine_subsystem if ai else '?'} | {route}"
            )
        return self._post("\n".join(lines))

    # ----- helpers ----------------------------------------------------------
    def _post(self, text: str) -> tuple[bool, str]:
        """Send one message. Never raises: problems come back as (False, reason)."""
        if not self.is_configured():
            logger.warning("Telegram not configured - dry run only")
            return False, "DRY RUN (Telegram not configured)"
        try:
            response = requests.post(
                self._url_template.format(token=self._token),
                data={"chat_id": self._chat_id, "text": text},
                timeout=10,
            )
            if response.status_code != 200:
                logger.error("Telegram returned %s: %s",
                             response.status_code, response.text[:200])
                return False, f"Telegram error {response.status_code}"

            body = response.json()
            if isinstance(body, dict) and body.get("ok") is True:
                logger.info("Telegram message sent")
                return True, "Sent"

            description = (
                body.get("description", "Telegram rejected the message")
                if isinstance(body, dict)
                else "Telegram returned an invalid response"
            )
            logger.error("Telegram rejected the message: %s", description)
            return False, f"Telegram rejected the message: {description}"
        except requests.RequestException as error:
            logger.error("Telegram request failed: %s", error)
            return False, "Could not reach Telegram"

    def _build_alert_message(self, log: ErrorLog) -> str:
        ai = log.ai_assessment
        # Uses the human-reviewed severity/risk when there is one.
        assessment = log.effective_assessment()
        decision = log.decision
        title = ("🚨 URGENT MACHINE ERROR" if decision and decision.notify_now
                 else "📋 MACHINE ERROR")
        return (
            f"{title}\n"
            f"Machine: {log.machine_id} ({log.machine_type})\n"
            f"Time: {log.timestamp}\n"
            f"Severity: {assessment.severity if assessment else '?'}/5  |  "
            f"Priority: {decision.score if decision else '?'}/100\n"
            f"Patient safety risk: "
            f"{'YES' if assessment and assessment.patient_safety_risk else 'no'}\n"
            f"Problem: {ai.machine_subsystem if ai else 'unknown'}\n"
            f"Likely cause: {ai.root_cause_hypothesis if ai else 'unknown'}\n"
            f"Action required: {ai.recommended_action if ai else 'Inspect the machine'}\n"
            f"Ref: {log.log_id}"
        )

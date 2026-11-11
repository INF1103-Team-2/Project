"""io_manager_html_report_formatter.py - a self-contained HTML fleet report."""

from html import escape

from io_manager_report_formatter import ReportFormatter
from logic_manager_error_log import ErrorLog


class HTMLReportFormatter(ReportFormatter):
    """One HTML file with inline CSS: opens in any browser and prints cleanly."""

    ROUTE_COLOURS = {
        "immediate_escalation": "#C62828",
        "human_triage": "#6A1B9A",
        "ai_unavailable_manual_review": "#6D4C41",
        "recurring_fault_review": "#E65100",
        "standard_queue": "#1565C0",
        "scheduled_maintenance": "#2E7D32",
    }

    def __init__(self) -> None:
        self._css: str = """
:root{--ink:#1F2A44;--muted:#5B6478;--line:#E3E7EF;--bg:#F6F8FB}
*{box-sizing:border-box}
body{margin:0;font-family:Segoe UI,Arial,sans-serif;color:var(--ink);background:var(--bg)}
header{background:var(--ink);color:#fff;padding:28px 40px}
header h1{margin:0;font-size:26px}
header p{margin:6px 0 0;color:#C9D1E3;font-size:14px}
main{padding:28px 40px;max-width:1300px;margin:auto}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:28px}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px}
.card .num{font-size:30px;font-weight:700}
.card .label{color:var(--muted);font-size:13px;margin-top:4px}
.card.alert .num{color:#C62828}
section{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin-bottom:24px}
h2{font-size:18px;margin:0 0 14px}
.bar-row{display:grid;grid-template-columns:240px 1fr 40px;align-items:center;gap:12px;margin:8px 0;font-size:14px}
.bar{height:14px;border-radius:7px}
.track{background:var(--bg);border-radius:7px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;background:var(--bg);color:var(--muted);font-weight:600;padding:9px 10px;border-bottom:1px solid var(--line)}
td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
.pill{display:inline-block;padding:2px 9px;border-radius:10px;color:#fff;font-size:12px;white-space:nowrap}
.sev{font-weight:700}
.risk{color:#C62828;font-weight:700}
.empty{color:var(--muted)}
footer{color:var(--muted);font-size:12px;text-align:center;padding:10px 0 30px}
@media print{body{background:#fff}header{color:#000;background:#fff;border-bottom:2px solid #000}
 header p{color:#333}section,.card{break-inside:avoid}}
"""

    def name(self) -> str:
        return "HTML"

    def file_extension(self) -> str:
        return ".html"

    def format(self, summary: dict, logs: list[ErrorLog], generated_at: str) -> str:
        return (
            "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Biomedical Equipment Error Report</title>"
            f"<style>{self._css}</style></head><body>"
            "<header><h1>Biomedical Equipment Error Report</h1>"
            f"<p>Generated {escape(generated_at)} · JSON Derulo triage system</p></header>"
            "<main>"
            f"{self._cards(summary)}"
            f"{self._routes(summary)}"
            f"{self._repeat_offenders(summary)}"
            f"{self._records(logs)}"
            "</main><footer>Severity shown is the human-reviewed value where a review exists."
            "</footer></body></html>\n"
        )

    # ----- sections ---------------------------------------------------------
    def _cards(self, summary: dict) -> str:
        cards = [
            ("Records stored", summary.get("total", 0), ""),
            ("Patient safety flags", summary.get("safety_risk_count", 0), " alert"),
            ("Needing human review", summary.get("human_review_count", 0), ""),
            ("Mean priority score", summary.get("mean_score", 0), ""),
        ]
        body = "".join(
            f"<div class=\"card{extra}\"><div class=\"num\">{escape(str(value))}</div>"
            f"<div class=\"label\">{escape(label)}</div></div>"
            for label, value, extra in cards
        )
        return f"<div class=\"cards\">{body}</div>"

    def _routes(self, summary: dict) -> str:
        by_route = summary.get("by_route") or {}
        if not by_route:
            return "<section><h2>Records by route</h2><p class=\"empty\">No records yet.</p></section>"
        biggest = max(by_route.values())
        rows = []
        for route, count in sorted(by_route.items(), key=lambda item: (-item[1], item[0])):
            width = round(100 * count / biggest)
            colour = self.ROUTE_COLOURS.get(route, "#455A64")
            rows.append(
                f"<div class=\"bar-row\"><span>{escape(route)}</span>"
                f"<div class=\"track\"><div class=\"bar\" style=\"width:{width}%;"
                f"background:{colour}\"></div></div><b>{count}</b></div>"
            )
        return f"<section><h2>Records by route</h2>{''.join(rows)}</section>"

    def _repeat_offenders(self, summary: dict) -> str:
        offenders = summary.get("repeat_offenders") or []
        if not offenders:
            body = "<p class=\"empty\">No machine has repeated faults.</p>"
        else:
            body = ("<table><tr><th>Machine</th><th>Logs</th></tr>"
                    + "".join(f"<tr><td>{escape(str(machine))}</td><td>{count}</td></tr>"
                              for machine, count in offenders)
                    + "</table>")
        return f"<section><h2>Machines with repeat faults</h2>{body}</section>"

    def _records(self, logs: list[ErrorLog]) -> str:
        if not logs:
            return "<section><h2>All records</h2><p class=\"empty\">No records yet.</p></section>"
        rows = []
        for log in self.sort_by_priority(logs):
            decision = log.decision
            ai = log.ai_assessment
            assessment = log.effective_assessment()
            route = decision.route if decision else "-"
            colour = self.ROUTE_COLOURS.get(route, "#455A64")
            severity = self.severity_of(log)
            risk = assessment.patient_safety_risk if assessment else False
            risk_html = '<span class="risk">YES</span>' if risk else "no"
            rows.append(
                "<tr>"
                f"<td><b>{escape(log.machine_id)}</b><br>{escape(log.machine_type)}</td>"
                f"<td>{escape(log.timestamp.replace('T', ' '))}<br>"
                f"<span class=\"empty\">{escape(log.log_id)}</span></td>"
                f"<td>{escape(log.error_code)}</td>"
                f"<td>{escape(log.raw_message)}</td>"
                f"<td class=\"sev\">{severity if severity is not None else '-'}/5</td>"
                f"<td>{risk_html}</td>"
                f"<td>{decision.score if decision else '-'}</td>"
                f"<td><span class=\"pill\" style=\"background:{colour}\">{escape(route)}</span></td>"
                f"<td>{escape(ai.recommended_action) if ai else escape(log.ai_error or '-')}</td>"
                f"<td>{escape(self.status_of(log))}</td>"
                "</tr>"
            )
        header = ("<tr><th>Machine</th><th>Logged / ref</th><th>Code</th><th>Message</th>"
                  "<th>Sev</th><th>Safety</th><th>Score</th><th>Route</th>"
                  "<th>Recommended action</th><th>Status</th></tr>")
        return (f"<section><h2>All records ({len(logs)})</h2>"
                f"<table>{header}{''.join(rows)}</table></section>")

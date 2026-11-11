"""io_manager_markdown_report_formatter.py - the fleet report as Markdown text."""

from io_manager_report_formatter import ReportFormatter
from logic_manager_error_log import ErrorLog


class MarkdownReportFormatter(ReportFormatter):
    """Plain-text report that reads well on GitHub or in any editor."""

    def name(self) -> str:
        return "Markdown"

    def file_extension(self) -> str:
        return ".md"

    def format(self, summary: dict, logs: list[ErrorLog], generated_at: str) -> str:
        lines = [
            "# Biomedical Equipment Error Report",
            "",
            f"_Generated {generated_at} · JSON Derulo triage system_",
            "",
            "## Summary",
            "",
            "| Measure | Value |",
            "|---|---|",
            f"| Records stored | {summary.get('total', 0)} |",
            f"| Patient safety flags | {summary.get('safety_risk_count', 0)} |",
            f"| Needing human review | {summary.get('human_review_count', 0)} |",
            f"| Mean priority score | {summary.get('mean_score', 0)} |",
            "",
            "## Records by route",
            "",
        ]
        by_route = summary.get("by_route") or {}
        if by_route:
            lines += ["| Route | Records |", "|---|---|"]
            lines += [f"| {route} | {count} |"
                      for route, count in sorted(by_route.items(), key=lambda i: (-i[1], i[0]))]
        else:
            lines.append("No records yet.")

        lines += ["", "## Machines with repeat faults", ""]
        offenders = summary.get("repeat_offenders") or []
        if offenders:
            lines += ["| Machine | Logs |", "|---|---|"]
            lines += [f"| {self._cell(machine)} | {count} |" for machine, count in offenders]
        else:
            lines.append("No machine has repeated faults.")

        lines += ["", f"## All records ({len(logs)})", ""]
        if logs:
            lines += ["| Machine | Logged | Code | Sev | Safety | Score | Route | Status |",
                      "|---|---|---|---|---|---|---|---|"]
            for log in self.sort_by_priority(logs):
                decision = log.decision
                assessment = log.effective_assessment()
                severity = self.severity_of(log)
                lines.append(
                    f"| {self._cell(log.machine_id)} | {log.timestamp.replace('T', ' ')} "
                    f"| {self._cell(log.error_code)} "
                    f"| {severity if severity is not None else '-'}/5 "
                    f"| {'**YES**' if assessment and assessment.patient_safety_risk else 'no'} "
                    f"| {decision.score if decision else '-'} "
                    f"| {decision.route if decision else '-'} "
                    f"| {self.status_of(log)} |"
                )
        else:
            lines.append("No records yet.")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _cell(value: str) -> str:
        """Stop a '|' inside the data from breaking the table."""
        return str(value).replace("|", "\\|")

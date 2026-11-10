"""logic_manager_fleet_analyzer.py - fleet-level summary of stored error logs."""

from logic_manager_error_log import ErrorLog


class FleetAnalyzer:
    """Aggregates many ErrorLogs: which routes, which machines keep failing."""

    REPEAT_OFFENDER_THRESHOLD = 2

    def summarise(self, logs: list[ErrorLog]) -> dict:
        total = len(logs)
        if total == 0:
            return {
                "total": 0,
                "safety_risk_count": 0,
                "human_review_count": 0,
                "mean_score": 0,
                "by_route": {},
                "repeat_offenders": [],
            }

        by_route: dict[str, int] = {}
        machine_counts: dict[str, int] = {}
        safety_risk_count = 0
        human_review_count = 0
        score_total = 0

        for log in logs:
            decision = log.decision
            route = decision.route if decision else "unrouted"
            by_route[route] = by_route.get(route, 0) + 1

            machine_id = log.machine_id or "unknown"
            machine_counts[machine_id] = machine_counts.get(machine_id, 0) + 1

            # A human review overrides the AI's safety-risk flag.
            assessment = log.effective_assessment()
            if assessment is not None and assessment.patient_safety_risk:
                safety_risk_count += 1
            if decision and decision.requires_human_review:
                human_review_count += 1
            score_total += int(decision.score) if decision else 0

        repeat_offenders = sorted(
            [(machine, count) for machine, count in machine_counts.items()
             if count >= self.REPEAT_OFFENDER_THRESHOLD],
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

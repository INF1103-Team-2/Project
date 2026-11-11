# Biomedical Equipment Error Report

_Generated 2026-11-07 01:53 · JSON Derulo triage system_

## Summary

| Measure | Value |
|---|---|
| Records stored | 11 |
| Patient safety flags | 6 |
| Needing human review | 1 |
| Mean priority score | 60.2 |

## Records by route

| Route | Records |
|---|---|
| immediate_escalation | 6 |
| scheduled_maintenance | 2 |
| ai_unavailable_manual_review | 1 |
| recurring_fault_review | 1 |
| standard_queue | 1 |

## Machines with repeat faults

| Machine | Logs |
|---|---|
| CT-114 | 4 |

## All records (11)

| Machine | Logged | Code | Sev | Safety | Score | Route | Status |
|---|---|---|---|---|---|---|---|
| CT-114 | 2026-10-09 10:00:00 | E555 | 5/5 | **YES** | 90 | immediate_escalation | Engineer notified |
| CT-114 | 2026-10-09 08:00:00 | E102 | 5/5 | **YES** | 90 | immediate_escalation | Engineer notified |
| CT-114 | 2026-10-09 08:04:00 | E102 | 5/5 | **YES** | 90 | immediate_escalation | Bundled with earlier alert |
| CT-114 | 2026-10-09 08:30:00 | E102 | 5/5 | **YES** | 90 | immediate_escalation | Engineer notified |
| XR-013 | 2026-10-09 10:05:00 | P100 | 5/5 | **YES** | 90 | immediate_escalation | Engineer notified |
| XR-010 | 2026-10-09 09:20:00 | U555 | 4/5 | **YES** | 76 | immediate_escalation | Engineer notified |
| XR-008 | 2026-10-09 09:00:00 | W210 | 3/5 | no | 52 | recurring_fault_review | Engineer notified |
| XR-012 | 2026-10-09 09:50:00 | S333 | 3/5 | no | 42 | standard_queue | Engineer notified |
| XR-011 | 2026-10-09 09:40:00 | F777 | 2/5 | no | 28 | scheduled_maintenance | Scheduled 2026-10-15 07:00:00 |
| XR-009 | 2026-10-09 09:10:00 | C001 | 1/5 | no | 14 | scheduled_maintenance | Scheduled 2026-10-15 07:00:00 |
| MRI-01 | 2026-10-09 09:30:00 | Z900 | -/5 | no | 0 | ai_unavailable_manual_review | Awaiting human review |

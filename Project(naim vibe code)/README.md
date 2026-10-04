# Biomedical Equipment Error Log Triage

INF1103 Team Project, Phase 1 — Procedural Foundation. Team 2.

Hospital biomedical engineering departments receive hundreds of free-text error
logs a day from infusion pumps, ventilators, monitors and imaging systems. Most
are noise. A few mean a device is about to fail on a patient. This CLI reads
those logs, has an AI model assess each one, applies triage rules to the
assessment, alerts an engineer when it matters, and keeps a consolidated record
of which machines keep failing.

---

## Pipeline

```
user / file  →  io_manager  →  ai_manager  →  logic_manager  →  data_manager
                    │                                              │
                    └──────────── Telegram alert ←─────────────────┘
```

| File | Responsibility |
|---|---|
| `io_manager.py` | Every `print()` and `input()` in the codebase. Input validation, all display functions, and the Telegram send (an output boundary). |
| `ai_manager.py` | `build_prompt` / `call_api` / `parse_response` / `validate_response`. No domain rules. |
| `logic_manager.py` | `evaluate` / `score` / `route` plus the triage rules. Pure: no I/O, no clock reads. |
| `data_manager.py` | `save` / `load` / `query`. JSON persistence with graceful failure. |
| `main.py` | Wires the pipeline. No direct terminal interaction. |

---

## Setup

```bash
cp .env.example .env      # then add your AI_API_KEY
pip install -r requirements.txt
python main.py
```

A free Gemini key from https://aistudio.google.com/apikey works out of the box.
Any OpenAI-compatible provider (Groq, OpenRouter, Ollama, OpenAI) works by
changing `AI_BASE_URL` and `AI_MODEL` in `.env` — no code changes.

### Docker

```bash
docker build -t inf1103-triage .
docker run -it --env-file .env -v "$(pwd)/data:/app/data" inf1103-triage
```

The test suite runs during `docker build`, so a broken build fails early.

### Tests

```bash
python tests/test_logic.py
```

56 assertions, no API key and no network needed. Covers every routing rule,
scoring, scheduling, response parsing, schema validation, persistence and
determinism.

---

## Why the AI is the core engine (C2)

Delete `ai_manager.py` and this application cannot do its job. Nothing else
produces `severity`, `machine_subsystem`, `patient_safety_risk`,
`recurrence_indicator` or `confidence` — and every rule in `logic_manager`
reads at least two of those fields. There is deliberately no keyword-matching
fallback. A record that fails AI enrichment is routed to
`ai_unavailable_manual_review` and flagged for a human; it is never
auto-triaged.

## Business rules

Evaluated in priority order, first match wins. Each of R1–R4 is a
multi-condition rule reading two or more AI output fields.

| Rule | Condition | Route |
|---|---|---|
| R1 | `severity >= 4` AND `patient_safety_risk` AND `confidence >= 0.7` | `immediate_escalation` — alert now |
| R2 | `severity >= 4` AND `confidence < 0.7` | `human_triage` — never page an engineer on a low-confidence guess |
| R3 | `recurrence_indicator` AND `severity >= 3` | `recurring_fault_review` — alert next morning |
| R4 | `severity <= 2` AND NOT `patient_safety_risk` | `scheduled_maintenance` — batched |
| — | anything else | `standard_queue` |

Priority score (0–100): `severity × 14`, `+20` if a patient safety risk, `+10`
if recurring, `−15` if confidence is below 0.5.

Deferred alerts are scheduled for 07:00 on the target day so nobody is paged
overnight for a cosmetic fault.

## Determinism (C4)

- API temperature pinned to `0`.
- `log_id` is a SHA-1 of the log content, not a counter or a timestamp.
- `save()` replaces by `log_id`, so reprocessing the same log leaves one row.
- The data file is always written sorted by `log_id` with sorted keys.
- `logic_manager` takes `now` as a parameter, so scheduling is a pure function
  of its inputs and is pinned in tests.

Verified by the `Two runs on the same input produce byte-identical files` test.

## Exception handling matrix

| Failure | Where handled | Behaviour |
|---|---|---|
| API connection failure / timeout | `ai_manager.call_api` | Caught per exception type, logged, returns `None`. Up to 3 attempts with backoff, then routed to manual review. Never crashes. |
| Malformed API response | `ai_manager.parse_response`, `validate_response` | Fences and surrounding prose stripped; missing keys, wrong types and out-of-range values rejected before any field is used. Triggers a retry. |
| Missing API key | `ai_manager.enrich_record` | Detected as a configuration fault, no retry, record flagged for manual review. |
| Corrupt or missing data file | `data_manager.load` | Logged, returns `[]`, program continues. Non-list contents and malformed rows also rejected. |
| Unwritable data file | `data_manager._write_all` | Atomic temp-file write; on failure the original file is left intact and `save` returns `False`. |
| Invalid user input | `io_manager.prompt_*` | Type, range, pattern and length validated; rejected with a message and re-prompted in a loop. |
| Malformed log file line | `io_manager.read_log_file` | Line skipped and reported; the rest of the batch still processes. |
| Telegram unreachable | `io_manager.send_alert` | Logged, user informed, record already saved. |
| Filter function raises during a query | `data_manager.query` | That record is skipped and logged; the search completes. |
| Anything unhandled | `main.main` | Caught per menu action, logged with a traceback to `logs/app.log`, returns to the menu. |

## Log file format

```
timestamp | machine_id | machine_type | error message
2026-09-14T03:12:44 | PUMP-114 | infusion_pump | Downstream occlusion alarm repeated 6x
```

`sample_data/sample_error_logs.txt` includes two deliberately broken lines to
demonstrate that malformed input is skipped rather than fatal.

## Constraint compliance

| # | Constraint | How |
|---|---|---|
| C1 | 100% procedural | No `class` keyword anywhere. Verify: `grep -rn "^\s*class " --include=*.py .` |
| C2 | AI is the core engine | See above. |
| C3 | Structured API responses | Prompt specifies the JSON schema; `validate_response` enforces keys, types and ranges. |
| C4 | Flat file persistence | JSON, deterministic. |
| C5 | Runs in Docker | `Dockerfile` in repo root; tests run at build time. |
| C6 | Meaningful Git history | Commit per function group — see the suggested sequence in the team notes. |

Verify C1 and the `print()` confinement:

```bash
grep -rn "^\s*class " --include=*.py .                         # expect no output
grep -rn "print(\|input(" --include=*.py . | grep -v io_manager | grep -v tests
```

## Team

| Module | Owner |
|---|---|
| `io_manager.py` | Zoey |
| `ai_manager.py` | Jing Jie, Owen |
| `logic_manager.py` | Jia Yi, Nam |
| `data_manager.py` | Subin |

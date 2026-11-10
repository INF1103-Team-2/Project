"""io_manager_gui_window.py - the desktop window (Tkinter): widgets, dialogs, display.

Advanced feature (Phase 2). The window only shows things and asks questions;
what happens when a button is pressed is decided by main_gui_app.GuiApp.

Thread safety: Tkinter widgets may only be touched from the main thread.
Anything that can be called from a worker thread (display_*, show_alert)
puts a job on a queue that the main thread drains every 100 ms.
"""

import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from io_manager_output_view import OutputView
from logic_manager_error_log import ErrorLog


class GuiWindow(OutputView):
    """Main application window; implements OutputView for the shared pipeline."""

    NAVY = "#1F2A44"
    MUTED = "#5B6478"
    BG = "#F6F8FB"
    ROUTE_ROW_COLOURS = {
        "immediate_escalation": "#FDE2E2",
        "human_triage": "#EFE3F7",
        "ai_unavailable_manual_review": "#EFE7E3",
        "recurring_fault_review": "#FFEBD9",
        "standard_queue": "#E3EEFB",
        "scheduled_maintenance": "#E3F4E5",
    }
    FILTERS = ("All records", "Immediate escalations", "Patient safety risk",
               "Needing human review")

    def __init__(self) -> None:
        self._root: tk.Tk = tk.Tk()
        self._root.title("JSON Derulo - Biomedical Equipment Error Log Triage")
        self._root.geometry("1320x820")
        self._root.minsize(1100, 680)
        self._root.configure(bg=self.BG)
        self._jobs: queue.Queue = queue.Queue()
        self._busy_count: int = 0
        self._shown_logs: dict[str, ErrorLog] = {}
        self._actions: dict[str, Callable] = {}
        self._buttons: list[ttk.Button] = []
        self._style()
        self._build()
        self._root.after(100, self._drain_jobs)

    # ======================================================================
    # Layout
    # ======================================================================
    def _style(self) -> None:
        style = ttk.Style(self._root)
        style.theme_use("clam")
        style.configure(".", font=("Helvetica", 10), background=self.BG)
        style.configure("Header.TFrame", background=self.NAVY)
        style.configure("Header.TLabel", background=self.NAVY, foreground="white",
                        font=("Helvetica", 16, "bold"))
        style.configure("Sub.TLabel", background=self.NAVY, foreground="#C9D1E3")
        style.configure("Card.TFrame", background="white", relief="solid", borderwidth=1)
        style.configure("CardNum.TLabel", background="white", font=("Helvetica", 20, "bold"))
        style.configure("CardAlert.TLabel", background="white", foreground="#C62828",
                        font=("Helvetica", 20, "bold"))
        style.configure("CardText.TLabel", background="white", foreground=self.MUTED)
        style.configure("Accent.TButton", background=self.NAVY, foreground="white",
                        font=("Helvetica", 10, "bold"), padding=(12, 6))
        style.map("Accent.TButton", background=[("active", "#2F3E63"),
                                                ("disabled", "#9AA3B5")])
        style.configure("TButton", padding=(10, 6))
        style.configure("Treeview", rowheight=26, font=("Helvetica", 10))
        style.configure("Treeview.Heading", font=("Helvetica", 10, "bold"))
        style.configure("Section.TLabel", font=("Helvetica", 11, "bold"))

    def _build(self) -> None:
        header = ttk.Frame(self._root, style="Header.TFrame", padding=(20, 12))
        header.pack(fill="x")
        ttk.Label(header, text="Biomedical Equipment Error Log Triage",
                  style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text="JSON Derulo · AI-assisted triage for hospital machine errors",
                  style="Sub.TLabel").pack(anchor="w")

        toolbar = ttk.Frame(self._root, padding=(20, 12, 20, 4))
        toolbar.pack(fill="x")
        for key, label, style in (
                ("add", "+ Add error log", "Accent.TButton"),
                ("import", "Import log file", "TButton"),
                ("review", "Review pending", "TButton"),
                ("report", "Generate report", "TButton"),
                ("refresh", "Refresh", "TButton")):
            button = ttk.Button(toolbar, text=label, style=style,
                                command=lambda k=key: self._fire(k))
            button.pack(side="left", padx=(0, 8))
            self._buttons.append(button)
            if key == "review":
                self._review_button = button

        self._progress = ttk.Progressbar(toolbar, mode="indeterminate", length=120)
        self._progress.pack(side="right")
        self._busy_label = ttk.Label(toolbar, text="", foreground=self.MUTED)
        self._busy_label.pack(side="right", padx=8)

        cards = ttk.Frame(self._root, padding=(20, 8))
        cards.pack(fill="x")
        self._card_values: dict[str, ttk.Label] = {}
        for index, (key, label) in enumerate((
                ("total", "Records stored"), ("safety_risk_count", "Patient safety flags"),
                ("human_review_count", "Needing human review"),
                ("mean_score", "Mean priority score"))):
            card = ttk.Frame(cards, style="Card.TFrame", padding=(16, 10))
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 10, 0))
            cards.columnconfigure(index, weight=1)
            value = ttk.Label(card, text="0", style="CardAlert.TLabel"
                              if key == "safety_risk_count" else "CardNum.TLabel")
            value.pack(anchor="w")
            ttk.Label(card, text=label, style="CardText.TLabel").pack(anchor="w")
            self._card_values[key] = value

        filters = ttk.Frame(self._root, padding=(20, 8, 20, 4))
        filters.pack(fill="x")
        ttk.Label(filters, text="Show:").pack(side="left")
        self._filter = ttk.Combobox(filters, values=self.FILTERS, state="readonly", width=24)
        self._filter.current(0)
        self._filter.pack(side="left", padx=6)
        self._filter.bind("<<ComboboxSelected>>", lambda _e: self._fire("filter"))
        ttk.Label(filters, text="Machine ID:").pack(side="left", padx=(16, 0))
        self._machine_search = ttk.Entry(filters, width=16)
        self._machine_search.pack(side="left", padx=6)
        self._machine_search.bind("<Return>", lambda _e: self._fire("filter"))
        ttk.Button(filters, text="Search", command=lambda: self._fire("filter")).pack(side="left")
        self._count_label = ttk.Label(filters, text="", foreground=self.MUTED)
        self._count_label.pack(side="right")

        log_frame = ttk.Frame(self._root, padding=(20, 0, 20, 12))
        log_frame.pack(side="bottom", fill="x")
        ttk.Label(log_frame, text="Activity", style="Section.TLabel").pack(anchor="w")
        self._activity = tk.Text(log_frame, height=7, wrap="word", relief="solid",
                                 borderwidth=1, font=("Courier", 9), padx=8, pady=4)
        self._activity.pack(fill="x", pady=(4, 0))
        self._activity.tag_configure("error", foreground="#C62828")
        self._activity.tag_configure("alert", foreground="#C62828", font=("Courier", 9, "bold"))
        self._activity.configure(state="disabled")

        body = ttk.PanedWindow(self._root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=20, pady=(4, 8))

        table_frame = ttk.Frame(body)
        columns = ("machine", "logged", "code", "sev", "score", "route", "status")
        self._table = ttk.Treeview(table_frame, columns=columns, show="headings",
                                   selectmode="browse")
        for column, title, width in (
                ("machine", "Machine", 85), ("logged", "Logged", 150), ("code", "Code", 60),
                ("sev", "Sev", 45), ("score", "Score", 55),
                ("route", "Route", 200), ("status", "Status", 170)):
            self._table.heading(column, text=title)
            self._table.column(column, width=width, anchor="w", stretch=column == "route")
        for route, colour in self.ROUTE_ROW_COLOURS.items():
            self._table.tag_configure(route, background=colour)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self._table.yview)
        self._table.configure(yscrollcommand=scroll.set)
        self._table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._table.bind("<<TreeviewSelect>>", lambda _e: self._fire_select())
        body.add(table_frame, weight=3)

        details_frame = ttk.Frame(body, padding=(10, 0, 0, 0))
        ttk.Label(details_frame, text="Record details", style="Section.TLabel").pack(anchor="w")
        self._details = tk.Text(details_frame, wrap="word", width=46, relief="solid",
                                borderwidth=1, font=("Courier", 10), padx=10, pady=8)
        self._details.pack(fill="both", expand=True, pady=(4, 0))
        self._details.configure(state="disabled")
        body.add(details_frame, weight=2)


    # ======================================================================
    # Wiring
    # ======================================================================
    def bind_actions(self, actions: dict[str, Callable]) -> None:
        """Keys: add, import, review, report, refresh, filter, select, close."""
        self._actions = dict(actions)
        if "close" in actions:
            self._root.protocol("WM_DELETE_WINDOW", self._close)

    def _fire(self, key: str) -> None:
        action = self._actions.get(key)
        if action is not None:
            action()

    def _fire_select(self) -> None:
        selected = self._table.selection()
        if selected and "select" in self._actions:
            self._actions["select"](self._shown_logs.get(selected[0]))

    def _close(self) -> None:
        self._actions["close"]()
        self._root.destroy()

    def run(self) -> None:
        self._root.mainloop()

    def current_filter(self) -> tuple[str, str]:
        return self._filter.get(), self._machine_search.get().strip()

    # ======================================================================
    # OutputView (safe to call from any thread)
    # ======================================================================
    def display_message(self, text: str) -> None:
        self._jobs.put(lambda: self._append_activity(text))

    def display_error(self, text: str) -> None:
        self._jobs.put(lambda: self._append_activity(f"! {text}", "error"))

    def display_result(self, log: ErrorLog) -> None:
        route = log.decision.route if log.decision else "unknown"
        score = log.decision.score if log.decision else "-"
        line = f"-> {log.machine_id}: {route} (score {score}/100)"
        self._jobs.put(lambda: self._append_activity(line))

    def show_alert(self, text: str) -> None:
        """Urgent alert pop-up (used by GuiNotifier)."""
        def job() -> None:
            self._append_activity("*** ALERT *** " + text.splitlines()[0], "alert")
            messagebox.showwarning("Urgent machine error", text, parent=self._root)
        self._jobs.put(job)

    def _append_activity(self, text: str, tag: str = "") -> None:
        self._activity.configure(state="normal")
        stamp = datetime.now().strftime("%H:%M:%S")
        self._activity.insert("end", f"[{stamp}] {text}\n", tag)
        self._activity.see("end")
        self._activity.configure(state="disabled")

    def _drain_jobs(self) -> None:
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                break
            job()
        self._root.after(100, self._drain_jobs)

    # ======================================================================
    # Background work
    # ======================================================================
    def run_background(self, label: str, task: Callable[[], object],
                       on_done: Callable[[object], None]) -> None:
        """Run slow work (AI calls, Telegram) off the main thread, then call on_done."""
        self._set_busy(True, label)

        def worker() -> None:
            try:
                result = task()
            except Exception as error:   # never let a worker kill the window
                self.display_error(f"Something went wrong ({error}).")
                result = None
            self._jobs.put(lambda: (self._set_busy(False), on_done(result)))

        threading.Thread(target=worker, daemon=True).start()

    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._busy_count += 1 if busy else -1
        working = self._busy_count > 0
        for button in self._buttons:
            button.state(["disabled"] if working else ["!disabled"])
        if working:
            self._busy_label.configure(text=label)
            self._progress.start(12)
        else:
            self._busy_label.configure(text="")
            self._progress.stop()

    # ======================================================================
    # Showing data
    # ======================================================================
    def show_records(self, logs: list[ErrorLog]) -> None:
        self._table.delete(*self._table.get_children())
        self._shown_logs = {}
        for log in logs:
            decision = log.decision
            assessment = log.effective_assessment()
            route = decision.route if decision else "-"
            self._table.insert("", "end", iid=log.log_id, tags=(route,), values=(
                log.machine_id,
                log.timestamp.replace("T", " "),
                log.error_code,
                f"{assessment.severity}/5" if assessment else "-",
                decision.score if decision else "-",
                route,
                self._status_of(log),
            ))
            self._shown_logs[log.log_id] = log
        self._count_label.configure(text=f"{len(logs)} record(s) shown")

    def show_summary(self, summary: dict) -> None:
        for key, label in self._card_values.items():
            label.configure(text=str(summary.get(key, 0)))

    def set_pending_count(self, count: int) -> None:
        self._review_button.configure(text=f"Review pending ({count})")

    def select(self, log_id: str) -> None:
        if self._table.exists(log_id):
            self._table.selection_set(log_id)
            self._table.see(log_id)

    def show_details(self, log: Optional[ErrorLog]) -> None:
        self._details.configure(state="normal")
        self._details.delete("1.0", "end")
        if log is not None:
            self._details.insert("end", self._format_details(log))
        self._details.configure(state="disabled")

    @staticmethod
    def _status_of(log: ErrorLog) -> str:
        decision = log.decision
        if decision is None:
            return "Not triaged"
        if decision.requires_human_review:
            return "Awaiting human review"
        if decision.suppressed_by:
            return "Bundled with earlier alert"
        if decision.notification_sent:
            return "Engineer notified"
        if decision.notify_now:
            return "Urgent - not delivered"
        return "Scheduled " + decision.scheduled_send_time.replace("T", " ")[:16]

    @staticmethod
    def _format_details(log: ErrorLog) -> str:
        lines = [
            f"{log.machine_id}  ({log.machine_type})",
            f"Ref        : {log.log_id}",
            f"Logged at  : {log.timestamp}",
            f"Reported by: {log.reported_by}",
            f"Error code : {log.error_code}",
            "",
            "Message:",
            f"  {log.raw_message}",
            "",
        ]
        ai = log.ai_assessment
        if ai is not None:
            lines += [
                "--- AI assessment ---",
                f"Subsystem   : {ai.machine_subsystem}",
                f"Severity    : {ai.severity}/5",
                f"Safety risk : {'YES' if ai.patient_safety_risk else 'no'}",
                f"Recurring   : {'YES' if ai.recurrence_indicator else 'no'}",
                f"Confidence  : {ai.confidence()}",
                f"Likely cause: {ai.root_cause_hypothesis}",
                f"Action      : {ai.recommended_action}",
                "",
            ]
        else:
            lines += [f"--- AI assessment unavailable: {log.ai_error or 'unknown reason'}", ""]
        human = log.human_assessment
        if human is not None:
            lines += [
                "--- Human-approved assessment ---",
                f"Severity    : {human.severity}/5",
                f"Safety risk : {'YES' if human.patient_safety_risk else 'no'}",
                f"Reviewed at : {human.reviewed_at}",
                "",
            ]
        decision = log.decision
        if decision is not None:
            lines += [
                "--- Triage decision ---",
                f"Route       : {decision.route}",
                f"Priority    : {decision.score}/100",
                f"Notify now  : {'YES' if decision.notify_now else 'no'}",
                f"Alert due   : {decision.scheduled_send_time}",
                f"Human review: {'YES' if decision.requires_human_review else 'no'}",
                "Rules fired :",
            ] + [f"  - {rule}" for rule in decision.rules_fired]
        return "\n".join(lines)

    # ======================================================================
    # Dialogs (main thread only)
    # ======================================================================
    def show_info(self, title: str, text: str) -> None:
        messagebox.showinfo(title, text, parent=self._root)

    def show_error(self, title: str, text: str) -> None:
        messagebox.showerror(title, text, parent=self._root)

    def ask_file_path(self) -> Optional[str]:
        path = filedialog.askopenfilename(
            parent=self._root, title="Choose a machine log file",
            filetypes=[("Log files", "*.txt *.log"), ("All files", "*.*")])
        return path or None

    def offer_open(self, path: str) -> None:
        if messagebox.askyesno("Report saved", f"Report saved to:\n{path}\n\nOpen it now?",
                               parent=self._root):
            webbrowser.open(Path(path).resolve().as_uri())

    def ask_report_format(self, format_names: list[str]) -> Optional[str]:
        dialog, frame = self._dialog("Generate report")
        ttk.Label(frame, text="Choose a report format:", style="Section.TLabel").pack(anchor="w")
        choice = tk.StringVar(value=format_names[0] if format_names else "")
        for name in format_names:
            ttk.Radiobutton(frame, text=name, value=name, variable=choice).pack(anchor="w", pady=2)
        result: dict[str, Optional[str]] = {"value": None}

        def ok() -> None:
            result["value"] = choice.get()
            dialog.destroy()
        self._dialog_buttons(frame, dialog, ok, "Generate")
        self._root.wait_window(dialog)
        return result["value"]

    def ask_new_log(self) -> Optional[ErrorLog]:
        """Form with the same validation rules as the console prompts."""
        dialog, frame = self._dialog("Add error log")
        entries: dict[str, ttk.Entry] = {}
        rows = (("machine_id", "Machine ID (e.g. CT-114)"), ("error_code", "Error code (e.g. E102)"),
                ("timestamp", "Timestamp (YYYY-MM-DDTHH:MM:SS)"), ("reported_by", "Reported by"))
        for row, (key, label) in enumerate(rows):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
            entry = ttk.Entry(frame, width=36)
            entry.grid(row=row, column=1, sticky="we", pady=4)
            entries[key] = entry
        entries["timestamp"].insert(0, datetime.now().strftime(ErrorLog.TIME_FORMAT))
        ttk.Label(frame, text="Machine type").grid(row=4, column=0, sticky="w", pady=4)
        machine_type = ttk.Combobox(frame, values=ErrorLog.MACHINE_TYPES, state="readonly")
        machine_type.current(0)
        machine_type.grid(row=4, column=1, sticky="we", pady=4)
        ttk.Label(frame, text="Error message").grid(row=5, column=0, sticky="nw", pady=4)
        message = tk.Text(frame, width=36, height=4, wrap="word", relief="solid", borderwidth=1)
        message.grid(row=5, column=1, sticky="we", pady=4)
        problem = ttk.Label(frame, text="", foreground="#C62828", wraplength=420)
        problem.grid(row=6, column=0, columnspan=2, sticky="w")
        entries["machine_id"].focus_set()
        result: dict[str, Optional[ErrorLog]] = {"log": None}

        def submit() -> None:
            machine_id = entries["machine_id"].get().strip()
            error_code = entries["error_code"].get().strip()
            timestamp = ErrorLog.parse_timestamp(entries["timestamp"].get().strip() or
                                                 datetime.now().strftime(ErrorLog.TIME_FORMAT))
            reported_by = entries["reported_by"].get().strip()
            text = message.get("1.0", "end").strip()
            error = None
            if not ErrorLog.MACHINE_ID_PATTERN.match(machine_id):
                error = "Machine ID must be 3-20 characters: letters, digits, hyphens or underscores."
            elif not ErrorLog.ERROR_CODE_PATTERN.match(error_code):
                error = "Error code must be 2-20 characters: letters, digits, hyphens or underscores."
            elif timestamp is None:
                error = "Could not read that date. Try 2026-09-14T03:12:44."
            elif not reported_by or len(reported_by) > 40:
                error = "Reported by is required (max 40 characters)."
            elif len(text) < ErrorLog.MIN_MESSAGE_LENGTH:
                error = f"Message too short - give at least {ErrorLog.MIN_MESSAGE_LENGTH} characters."
            elif len(text) > ErrorLog.MAX_MESSAGE_LENGTH:
                error = f"Message too long (max {ErrorLog.MAX_MESSAGE_LENGTH} characters)."
            if error:
                problem.configure(text=error)
                return
            result["log"] = ErrorLog(machine_id, error_code, machine_type.get(),
                                     timestamp, reported_by, text)
            dialog.destroy()

        self._dialog_buttons(frame, dialog, submit, "Send to AI", row=7)
        self._root.wait_window(dialog)
        return result["log"]

    def ask_review(self, log: ErrorLog, position: str) -> Optional[tuple]:
        """Return (severity, safety_risk, source), "skip", or None to stop."""
        dialog, frame = self._dialog(f"Human review {position}")
        ttk.Label(frame, text=f"{log.machine_id} - {log.error_code}",
                  style="Section.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text=log.raw_message, wraplength=460).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 8))
        ai = log.ai_assessment
        ai_text = (f"AI says: severity {ai.severity}/5, safety risk "
                   f"{'YES' if ai.patient_safety_risk else 'no'}, confidence {ai.confidence()}"
                   if ai else f"AI assessment unavailable: {log.ai_error or 'unknown reason'}")
        ttk.Label(frame, text=ai_text, foreground=self.MUTED, wraplength=460).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Label(frame, text="Your severity").grid(row=3, column=0, sticky="w")
        severity = tk.IntVar(value=ai.severity if ai else 3)
        scale = ttk.Frame(frame)
        scale.grid(row=3, column=1, columnspan=2, sticky="w")
        for value in range(1, 6):
            ttk.Radiobutton(scale, text=str(value), value=value, variable=severity).pack(
                side="left", padx=(0, 10))
        safety = tk.BooleanVar(value=ai.patient_safety_risk if ai else False)
        ttk.Checkbutton(frame, text="Patient-safety risk", variable=safety).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=6)
        result: dict[str, object] = {"value": None}

        def finish(value: object) -> None:
            result["value"] = value
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=3, sticky="e", pady=(10, 0))
        if ai is not None:
            ttk.Button(buttons, text="Approve AI severity", command=lambda: finish(
                (ai.severity, ai.patient_safety_risk, "ai_approved"))).pack(side="left", padx=4)
        ttk.Button(buttons, text="Save my assessment", style="Accent.TButton",
                   command=lambda: finish((severity.get(), safety.get(), "human_assessed"))
                   ).pack(side="left", padx=4)
        ttk.Button(buttons, text="Leave pending", command=lambda: finish("skip")).pack(
            side="left", padx=4)
        ttk.Button(buttons, text="Stop reviewing", command=lambda: finish(None)).pack(
            side="left", padx=4)
        self._root.wait_window(dialog)
        return result["value"]

    def _dialog(self, title: str) -> tuple[tk.Toplevel, ttk.Frame]:
        dialog = tk.Toplevel(self._root)
        dialog.title(title)
        dialog.transient(self._root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        dialog.grab_set()
        return dialog, frame

    @staticmethod
    def _dialog_buttons(frame: ttk.Frame, dialog: tk.Toplevel, on_ok: Callable,
                        ok_text: str, row: Optional[int] = None) -> None:
        buttons = ttk.Frame(frame)
        if row is None:
            buttons.pack(anchor="e", pady=(12, 0))
        else:
            buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text=ok_text, style="Accent.TButton", command=on_ok).pack(side="right")

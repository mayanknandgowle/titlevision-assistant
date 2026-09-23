"""Local Windows application. UI thread never owns Playwright objects."""
from datetime import datetime, timedelta
import os
from pathlib import Path
import queue
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from engine import Engine, PreviewRow
from journal import Journal
from rules import COMMENT, EASTERN, NeedsAttention, Order, Plan, Stopped, Workflow
from titlevision import TitleVision
from sla import REASONS, approve_reason
from sla_engine import SLAEngine
from appmeta import VERSION, UPDATE_REPOSITORY
from paths import user_data_dir, migrate_adjacent_history
from updates import UpdateError, check_update, download_update, trusted_installer, launch_installer

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
DATA_DIR = user_data_dir()
UPDATE_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TitleVisionAssistant" / "updates"


class Worker(threading.Thread):
    def __init__(self, events):
        super().__init__(daemon=True)
        self.events = events
        self.commands = queue.Queue()
        self.stop = threading.Event()

    def emit(self, name, data=None):
        self.events.put((name, data))

    def run(self):
        site = TitleVision()
        try:
            migrate_adjacent_history(APP_DIR, DATA_DIR)
            journal = Journal(DATA_DIR / "history.sqlite3")
        except Exception:
            self.emit("error", "Could not create local history. Move the app folder to a writable location.")
            return
        engine = Engine(site, journal, self.emit, self.stop)
        sla_engine = SLAEngine(site, journal, self.emit, self.stop)
        try:
            while True:
                name, value = self.commands.get()
                if name == "close":
                    return
                try:
                    if name == "open":
                        site.open()
                        self.emit("opened")
                    elif name == "preview":
                        (sla_engine if value == "sla" else engine).preview()
                        self.emit("preview_done")
                    elif name == "apply":
                        mode, rows = value
                        self.emit("apply_done", (sla_engine if mode == "sla" else engine).apply(rows))
                    elif name == "export":
                        journal.export(value)
                        self.emit("exported", value)
                    elif name == "import_history":
                        self.emit("history_imported", journal.import_history(value))
                    elif name == "check_update":
                        self.emit("update_checked", (check_update(), value))
                    elif name == "download_update":
                        path = download_update(value, UPDATE_DIR,
                            progress=lambda done, total: self.emit("progress", (done, total, f"Downloading update: {done * 100 // total}%")),
                            cancelled=self.stop.is_set)
                        self.emit("update_downloaded", (path, value, trusted_installer(path, value)))
                    elif name == "install_update":
                        path, release = value
                        site.close()
                        launch_installer(path, release)
                        self.emit("installer_started")
                except UpdateError as exc:
                    self.emit("update_error", (str(exc), name == "check_update" and value is True))
                except Stopped:
                    self.emit("stopped")
                except NeedsAttention as exc:
                    self.emit("error", str(exc))
                except Exception as exc:
                    # Do not persist page dumps, passwords, login URLs, or browser state.
                    self.emit("error", "The browser action could not finish (" + type(exc).__name__ + "). Check the browser and preview again. Any uncertain save is blocked from automatic retries.")
                finally:
                    self.emit("idle")
        finally:
            site.close()
            journal.close()
            self.emit("closed")


class App(tk.Tk):
    def __init__(self, demo=False):
        super().__init__()
        self.title("TitleVision Assistant")
        self.geometry(f"{min(1180, self.winfo_screenwidth()-60)}x{min(900, self.winfo_screenheight()-80)}")
        self.minsize(850, 600)
        self.configure(bg="#f2f5fa")
        self.events = queue.Queue()
        self.worker = Worker(self.events)
        self.rows = {}
        self.busy = False
        self.opened = False
        self.preview_complete = False
        self.demo = False
        self.closing = False
        self.available_release = None
        self._style()
        self._layout()
        self.worker.start()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)
        if demo:
            self._demo()
        else:
            self.after(2500, lambda: self._check_updates(automatic=True))

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 10), padding=(14, 9))
        style.configure("Primary.TButton", background="#2366d1", foreground="white", borderwidth=0)
        style.map("Primary.TButton", background=[("disabled", "#dce3ef"), ("active", "#1854b5")], foreground=[("disabled", "#778397")])
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=34, background="white", fieldbackground="white", borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#e9eef6", padding=(8, 10))
        style.map("Treeview", background=[("selected", "#e0ecff")], foreground=[("selected", "#17335c")])
        style.configure("Horizontal.TProgressbar", background="#2366d1", troughcolor="#e4eaf3", borderwidth=0)

    def _layout(self):
        # Keep all review controls reachable at Windows display scaling settings.
        canvas = tk.Canvas(self, bg="#f2f5fa", highlightthickness=0)
        vertical = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=canvas.xview)
        vertical.pack(side="right", fill="y")
        horizontal.pack(side="bottom", fill="x")
        canvas.pack(fill="both", expand=True)
        canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        body = tk.Frame(canvas, bg="#f2f5fa")
        body_id = canvas.create_window(0, 0, window=body, anchor="nw")
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(body_id, width=max(1050, event.width)))
        top = tk.Frame(body, bg="#142844", padx=28, pady=20)
        top.pack(fill="x")
        self.update_button = ttk.Button(top, text="↻  Check updates", command=self._check_updates)
        self.update_button.pack(side="right", anchor="n", padx=(12, 0))
        tk.Label(top, text="TITLEVISION ASSISTANT", font=("Segoe UI", 11, "bold"), fg="#a9c6f6", bg="#142844").pack(anchor="w")
        tk.Label(top, text="TitleVision ETA updates", font=("Segoe UI", 23, "bold"), fg="white", bg="#142844").pack(anchor="w", pady=(5, 2))
        self.mode = tk.StringVar(value="Ground orders")
        self.mode_choice = ttk.Combobox(top, textvariable=self.mode, state="readonly", width=38,
                                       values=("Ground orders", "Resolve expired SLA"))
        self.mode_choice.pack(anchor="w", pady=(4, 4))
        self.mode_choice.bind("<<ComboboxSelected>>", self._mode_changed)
        self.instructions = tk.StringVar(value="Preview blank ETA comments, then set each ETA to 5 PM Eastern.")
        tk.Label(top, textvariable=self.instructions, font=("Segoe UI", 11), fg="#d4dff0", bg="#142844").pack(anchor="w")
        self.account = tk.StringVar(value="Not connected  ·  Open the app's TitleVision browser")
        tk.Label(body, textvariable=self.account, bg="#f2f5fa", fg="#53627a", font=("Segoe UI", 10), padx=28, pady=12).pack(anchor="w")
        actions = tk.Frame(body, bg="#f2f5fa", padx=28)
        actions.pack(fill="x")
        self.open_button = ttk.Button(actions, text="1   Open TitleVision browser", command=self._open)
        self.open_button.pack(side="left", padx=(0, 8))
        self.preview_button = ttk.Button(actions, text="2   Preview orders", command=self._preview, state="disabled")
        self.preview_button.pack(side="left", padx=(0, 8))
        self.run_button = ttk.Button(actions, text="3   Run updates", style="Primary.TButton", command=self._apply, state="disabled")
        self.run_button.pack(side="left", padx=(0, 8))
        self.stop_button = ttk.Button(actions, text="Stop", command=self._stop, state="disabled")
        self.stop_button.pack(side="right")
        box = tk.Frame(body, bg="white", padx=16, pady=12, highlightbackground="#dce3ed", highlightthickness=1)
        box.pack(fill="x", padx=28, pady=(16, 12))
        tk.Label(box, text="WORKFLOW", bg="white", fg="#53627a", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.workflow_note = tk.StringVar(value=COMMENT)
        tk.Label(box, textvariable=self.workflow_note, bg="white", fg="#142844", font=("Segoe UI", 10), wraplength=1080, justify="left").pack(anchor="w", pady=(4, 0))
        metrics = tk.Frame(body, bg="#f2f5fa", padx=28)
        metrics.pack(fill="x", pady=(0, 8))
        self.metrics = tk.StringVar(value="Preview has not been run. Existing ETA comments are preserved.")
        tk.Label(metrics, textvariable=self.metrics, bg="#f2f5fa", fg="#22364f", font=("Segoe UI", 11, "bold")).pack(side="left")
        self.demo_button = ttk.Button(metrics, text="Try demo", command=self._demo)
        self.demo_button.pack(side="right")
        table_frame = tk.Frame(body, bg="white")
        table_frame.pack(fill="both", expand=True, padx=28)
        self.tree = ttk.Treeview(table_frame, columns=("order", "product", "eta", "status"), show="headings", selectmode="browse", height=4)
        for column, label, width in (("order", "Order", 265), ("product", "Product", 240), ("eta", "Proposed ETA · Eastern", 260), ("status", "Status", 140)):
            self.tree.heading(column, text=label, anchor="w")
            self.tree.column(column, width=width, minwidth=100, anchor="w")
        self.tree.tag_configure("Saved", foreground="#11643b")
        self.tree.tag_configure("Needs review", foreground="#9c5f06")
        self.tree.tag_configure("Skipped", foreground="#6b7280")
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        reason_bar = tk.Frame(body, bg="#f2f5fa", padx=28)
        reason_bar.pack(fill="x", pady=(8, 0))
        tk.Label(reason_bar, text="Delay reason", bg="#f2f5fa").pack(side="left", padx=(0, 8))
        self.reason = tk.StringVar()
        self.reason_choice = ttk.Combobox(reason_bar, textvariable=self.reason, values=tuple(REASONS), width=43, state="disabled")
        self.reason_choice.pack(side="left", padx=(0, 8))
        self.reason_choice.bind("<<ComboboxSelected>>", self._reason_changed)
        self.confirm_reason = ttk.Button(reason_bar, text="Confirm reason for this order", command=self._confirm_reason, state="disabled")
        self.confirm_reason.pack(side="left")
        self.detail = tk.StringVar(value="Select an order to see why it is ready, skipped, or needs review.")
        tk.Label(body, textvariable=self.detail, bg="#f2f5fa", fg="#53627a", font=("Segoe UI", 10), wraplength=1020, justify="left", anchor="w").pack(fill="x", padx=28, pady=(10, 6))
        comment_frame = tk.Frame(body)
        comment_frame.pack(fill="x", padx=28, pady=(0, 6))
        self.comment_preview = tk.Text(comment_frame, height=5, wrap="word", font=("Segoe UI", 10), relief="solid", borderwidth=1)
        self.comment_preview.pack(side="left", fill="x", expand=True)
        comment_scroll = ttk.Scrollbar(comment_frame, orient="vertical", command=self.comment_preview.yview)
        comment_scroll.pack(side="right", fill="y")
        self.comment_preview.configure(yscrollcommand=comment_scroll.set)
        self.comment_preview.configure(state="disabled")
        self.progress = ttk.Progressbar(body, mode="determinate")
        self.progress.pack(fill="x", padx=28, pady=6)
        self.status = tk.StringVar(value="Ready. Open the browser to get started.")
        tk.Label(body, textvariable=self.status, bg="#f2f5fa", fg="#22364f", font=("Segoe UI", 10), wraplength=1020, justify="left", anchor="w").pack(fill="x", padx=28)
        bottom = tk.Frame(body, bg="#f2f5fa", padx=28, pady=14)
        bottom.pack(fill="x")
        self.export_button = ttk.Button(bottom, text="Export update history", command=self._export)
        self.export_button.pack(side="left")
        self.import_button = ttk.Button(bottom, text="Import previous history", command=self._import_history)
        self.import_button.pack(side="left", padx=(8, 0))
        tk.Label(bottom, text=f"v{VERSION}  ·  Local app  ·  All times Eastern", bg="#f2f5fa", fg="#748094", font=("Segoe UI", 9)).pack(side="right")

    def _check_updates(self, automatic=False):
        if self.busy or self.closing:
            return
        self.status.set("Checking GitHub for a published update…")
        self._start("check_update", automatic)

    def _offer_update(self, release):
        if self.closing or self.busy:
            return
        if messagebox.askyesno("Update available", f"Version {release.version} is available (installed: {VERSION}).\n\n"
                f"Source: github.com/{UPDATE_REPOSITORY}\nDownload size: {release.size / 1048576:.1f} MB\n\n"
                "Download the Windows installer? Your order history will be retained.", parent=self):
            self._clear()
            self._start("download_update", release)

    def _offer_install(self, value):
        if self.closing or self.busy:
            return
        path, release, trusted = value
        if trusted:
            if messagebox.askyesno("Install update", "Download and publisher verified.\n\nClose this app and start the update installer?", parent=self):
                self._start("install_update", (path, release))
        else:
            messagebox.showinfo("Download verified", "The installer passed its SHA-256 check. Automatic installation is disabled because this build and installer do not have matching trusted publisher signatures.\n\n"
                f"Downloaded file:\n{path}\n\nReview the GitHub release and install manually if you trust its publisher.", parent=self)
            if messagebox.askyesno("Release details", "Open the official GitHub release page?", parent=self):
                webbrowser.open(release.page_url)

    def _mode_key(self):
        return "sla" if self.mode.get() == "Resolve expired SLA" else "ground"

    def _mode_changed(self, _event=None):
        self._clear()
        sla = self._mode_key() == "sla"
        self.instructions.set("Active & Available tasks: review expired ETAs, confirm reasons, then update." if sla else
                              "Preview blank ETA comments, then set each ETA to 5 PM Eastern.")
        self.workflow_note.set("Existing ETA + 5 weekdays (Monday–Friday), at 5 PM Eastern. No holidays are assumed. "
                               "Existing matching ETAs are edited; missing ETAs use the expired product SLA as the base. "
                               "Confirm each reason against the order before running updates." if sla else COMMENT)
        self.status.set("Preview orders to load the selected workflow.")
        self._buttons()

    def _show_comment(self, text):
        self.comment_preview.configure(state="normal")
        self.comment_preview.delete("1.0", "end")
        self.comment_preview.insert("1.0", text)
        self.comment_preview.configure(state="disabled")

    def _start(self, name, value=None):
        if self.busy:
            return
        self.busy = True
        self.worker.stop.clear()
        self._buttons()
        self.worker.commands.put((name, value))

    def _buttons(self):
        self.update_button.configure(state="disabled" if self.busy or self.closing else "normal")
        self.mode_choice.configure(state="disabled" if self.busy else "readonly")
        self.open_button.configure(state="disabled" if self.busy else "normal")
        self.preview_button.configure(state="normal" if self.opened and not self.busy else "disabled")
        ready = any(r.status == "Ready" for r in self.rows.values())
        self.run_button.configure(state="normal" if self.preview_complete and ready and not self.busy and not self.demo else "disabled")
        self.stop_button.configure(state="normal" if self.busy else "disabled")
        self.demo_button.configure(state="disabled" if self.busy else "normal")
        self.export_button.configure(state="disabled" if self.busy else "normal")
        self.import_button.configure(state="disabled" if self.busy else "normal")
        selection = self.tree.selection()
        row = self.rows.get(selection[0]) if selection else None
        can_confirm = (self._mode_key() == "sla" and not self.busy and self.preview_complete
                       and row is not None and row.plan is not None and row.status in {"Ready", "Confirm reason"})
        self.reason_choice.configure(state="readonly" if can_confirm else "disabled")
        self.confirm_reason.configure(state="normal" if can_confirm else "disabled")

    def _clear(self):
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        self.preview_complete = False
        self.metrics.set("Preview has not been run. Confirmed SLA updates edit matching ETAs." if self._mode_key() == "sla" else
                         "Preview has not been run. Existing ETA comments are preserved.")
        self.progress["value"] = 0
        self.detail.set("Select an order to see details.")
        self.reason.set("")
        self._show_comment("")

    def _open(self):
        self._clear()
        self.demo = False
        self.opened = False
        self.account.set("Opening your saved TitleVision browser session…")
        self.status.set("If needed, sign in directly on TitleVision. Passwords are not collected by this app.")
        self._start("open")

    def _preview(self):
        self._clear()
        self.demo = False
        self.status.set("Reading " + self.mode.get() + ". Preview does not change any ETA.")
        self._start("preview", self._mode_key())

    def _apply(self):
        self.preview_complete = False
        count = sum(r.status == "Ready" for r in self.rows.values())
        self.status.set(f"Updating {count} ready orders. Stop prevents the next submission; a submitted order is checked first.")
        self._start("apply", (self._mode_key(), list(self.rows.values())))

    def _stop(self):
        self.worker.stop.set()
        self.status.set("Stopping after the current browser action. Any submitted order will be verified first.")
        self.stop_button.configure(state="disabled")

    def _export(self):
        path = filedialog.asksaveasfilename(parent=self, title="Save update history", defaultextension=".csv", initialfile="TitleVision-update-history.csv", filetypes=[("CSV file", "*.csv")])
        if path:
            self._start("export", path)

    def _import_history(self):
        path = filedialog.askopenfilename(parent=self, title="Choose the previous app's data/history.sqlite3",
            filetypes=[("SQLite history", "*.sqlite3")])
        if path:
            self._clear()
            self._start("import_history", path)

    def _row(self, row):
        key = row.order.key
        self.rows[key] = row
        eta = row.plan.target.strftime("%b %d, %Y  ·  5:00 PM") if row.plan else "—"
        values = (row.order.number, row.plan.workflow.product if row.plan else row.order.product, eta, row.status)
        if self.tree.exists(key):
            self.tree.item(key, values=values, tags=(row.status,))
        else:
            self.tree.insert("", "end", iid=key, values=values, tags=(row.status,))

    def _selected(self, _event=None):
        selection = self.tree.selection()
        if selection:
            row = self.rows[selection[0]]
            self.detail.set(row.order.number + "  ·  " + row.detail)
            if row.plan and self._mode_key() == "sla":
                self.reason.set(row.plan.reason)
                self._preview_comment(row)
            else:
                self._show_comment(row.plan.comment if row.plan else "")
        self._buttons()

    def _preview_comment(self, row):
        plan = row.plan
        old = plan.old_reminder[1] if plan.old_reminder else "No existing ETA for this product."
        proposed = plan.comment if plan.reason else "Select the actual delay reason to preview the revised comment."
        self._show_comment(f"{row.order.state} / {row.order.county} · {row.order.client}\n"
                           f"Previous ETA: {datetime.fromisoformat(plan.base_eta):%m/%d/%Y %I:%M %p} Eastern\n"
                           f"New ETA: {plan.target:%m/%d/%Y %I:%M %p} Eastern\n"
                           f"Proposed comment: {proposed}\nPrevious comment: {old}\nReason source: {plan.reason_source}")

    def _reason_changed(self, _event=None):
        from dataclasses import replace
        selection = self.tree.selection()
        if not selection or self.busy:
            return
        row = self.rows[selection[0]]
        if row.plan and row.status in {"Ready", "Confirm reason"}:
            row.plan = replace(row.plan, reason=self.reason.get(), approved=False, reason_source="Selected; awaiting confirmation")
            row.status = "Confirm reason"
            self._row(row)
            self._preview_comment(row)
            self._buttons()

    def _confirm_reason(self):
        selection = self.tree.selection()
        if not selection or self.busy or not self.preview_complete:
            return
        row = self.rows[selection[0]]
        if not row.plan or self.reason.get() not in REASONS:
            self.status.set("Select the actual delay reason for this order first.")
            return
        row.plan = approve_reason(row.plan, self.reason.get())
        row.status = "Ready"
        row.detail = "Delay reason confirmed. " + ("Edit the existing ETA." if row.plan.old_reminder else "Add a missing ETA.")
        self._row(row)
        self._selected()
        self.status.set("Reason confirmed. Run updates applies all Ready rows.")

    def _demo(self):
        self.mode.set("Ground orders")
        self._mode_changed()
        self._clear()
        self.demo = True
        day = datetime.now(EASTERN) + timedelta(days=2)
        for i, product in enumerate(("Full Title", "Current Owner", "Legal & Vesting", "Update Full Title")):
            order = Order(f"DEMO-ORDER-{i+1:03}", product, "09/17/2026 10:00 AM", f"demo:{i}")
            workflow = Workflow(product, f"DEMO-{i}", order.arrival, "", "")
            plan = Plan(order, workflow, day.replace(hour=17, minute=0, second=0, microsecond=0), "DEMO", datetime.now(EASTERN))
            self._row(PreviewRow(order, "Ready" if i < 3 else "Needs review", "Sample only. No TitleVision orders are read or changed." if i < 3 else "Example: SLA/NB date is already past.", plan if i < 3 else None))
        self.metrics.set("DEMO  ·  3 ready  ·  1 needs review  ·  No real orders")
        self.status.set("Demo preview only. Run updates is disabled. Open the browser to use real orders.")
        self._buttons()

    def _poll(self):
        try:
            while True:
                name, value = self.events.get_nowait()
                if name == "opened":
                    self.opened = True
                    self.account.set("TitleVision browser opened  ·  Click Preview orders when signed in")
                    self.status.set("This dedicated profile retains browser data. TitleVision may still require sign-in when its session expires.")
                elif name == "update_checked":
                    release, automatic = value
                    self.available_release = release
                    self.update_button.configure(text=f"↻  Update {release.version}" if release else "↻  Check updates")
                    self.status.set(f"Version {release.version} is available. Click Check updates to download." if release else f"You are up to date (v{VERSION}).")
                    if release and not automatic:
                        self.after(150, lambda r=release: self._offer_update(r))
                    elif not release and not automatic and not self.closing:
                        messagebox.showinfo("Up to date", f"You are using the latest published version: {VERSION}.", parent=self)
                elif name == "update_downloaded":
                    self.status.set("Update downloaded and integrity verified.")
                    self.after(150, lambda v=value: self._offer_install(v))
                elif name == "update_error":
                    message, automatic = value
                    self.status.set(message)
                    if not automatic and not self.closing:
                        messagebox.showwarning("Update unavailable", message, parent=self)
                elif name == "installer_started":
                    self._close()
                elif name == "account":
                    self.account.set("Connected as " + value)
                elif name == "summary":
                    self.metrics.set(f"{value['total']} Ground orders  ·  {value['candidates']} blank comments  ·  {value['existing']} already have comments")
                elif name == "sla_summary":
                    self.metrics.set(f"{value['total']} Active/Available products · Checking expired SLA and existing ETA")
                elif name == "row":
                    self._row(value)
                elif name == "result":
                    key, status, detail = value
                    row = self.rows[key]
                    row.status, row.detail = status, detail
                    self._row(row)
                elif name == "progress":
                    done, total, text = value
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = done
                    self.status.set(text)
                elif name == "preview_done":
                    self.preview_complete = True
                    ready = sum(r.status == "Ready" for r in self.rows.values())
                    self.status.set("Preview complete. Select each eligible row and confirm its actual delay reason." if self._mode_key() == "sla" else
                                    (f"Preview complete: {ready} orders ready. Run updates applies all Ready rows." if ready else "Preview complete. No eligible blank ETA comments are ready to update."))
                elif name == "apply_done":
                    self.status.set(f"Finished: {value['saved']} saved, {value['skipped']} skipped, {value['review']} need review. Preview again to refresh the queue.")
                elif name == "exported":
                    self.status.set("Update history exported.")
                elif name == "history_imported":
                    self.status.set(f"Imported {value} previous history records. Existing records were preserved.")
                elif name == "stopped":
                    self.preview_complete = False
                    self.status.set("Stopped. Preview again to refresh orders before another run.")
                elif name == "error":
                    self.preview_complete = False
                    self.status.set(value)
                    if not self.closing:
                        messagebox.showwarning("Needs attention", value, parent=self)
                elif name == "idle":
                    self.busy = False
                    self._buttons()
                elif name == "closed":
                    self.destroy()
                    return
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(100, self._poll)

    def _close(self):
        if self.closing:
            return
        self.closing = True
        self.worker.stop.set()
        self.status.set("Closing after the current action and save verification finish…")
        self.worker.commands.put(("close", None))
        if not self.worker.is_alive():
            self.destroy()


if __name__ == "__main__":
    App(demo="--demo" in sys.argv).mainloop()

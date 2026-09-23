"""Commit intent is written before clicking Add; uncertain submissions are never retried."""
import csv
from datetime import datetime, timezone
import sqlite3
import json
from pathlib import Path
from contextlib import closing
from rules import NeedsAttention


class Journal:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS operations (
            order_key TEXT PRIMARY KEY, order_number TEXT NOT NULL,
            product TEXT NOT NULL, arrival TEXT NOT NULL, eta TEXT NOT NULL,
            status TEXT NOT NULL, detail TEXT NOT NULL, updated TEXT NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS sla_audit (
            operation_key TEXT PRIMARY KEY, account TEXT NOT NULL, order_key TEXT NOT NULL,
            before_json TEXT NOT NULL, comment TEXT NOT NULL, reason TEXT NOT NULL,
            policy TEXT NOT NULL)""")
        self.db.commit()

    def get(self, key):
        row = self.db.execute("SELECT status, detail FROM operations WHERE order_key=?", (key,)).fetchone()
        return row

    def reserve(self, plan):
        """Only one app instance may submit this order, even when both previewed it."""
        with self.db:
            # Serialize the pending check and reservation across app instances.
            self.db.execute("BEGIN IMMEDIATE")
            if hasattr(plan, "old_reminder") and self.pending_sla(plan.account, plan.order.key):
                return False
            cursor = self.db.execute("INSERT OR IGNORE INTO operations VALUES (?,?,?,?,?,?,?,?)", (
                plan.operation_key, plan.order.number, plan.workflow.product, plan.order.arrival,
                plan.target.isoformat(), "submitting", "Save is about to be clicked; do not retry automatically.",
                datetime.now(timezone.utc).isoformat()))
            inserted = cursor.rowcount == 1
            if inserted and hasattr(plan, "old_reminder"):
                self.db.execute("INSERT INTO sla_audit VALUES (?,?,?,?,?,?,?)", (
                    plan.operation_key, plan.account, plan.order.key,
                    json.dumps({"reminder": plan.old_reminder, "base_eta": plan.base_eta,
                                "sla": plan.workflow.sla, "state": plan.order.state,
                                "county": plan.order.county, "client": plan.order.client}),
                    plan.comment, plan.reason, plan.policy))
            return inserted

    def pending_sla(self, account, order_key):
        return self.db.execute("""SELECT 1 FROM sla_audit a JOIN operations o
            ON o.order_key=a.operation_key WHERE a.account=? AND a.order_key=?
            AND o.status IN ('submitting','uncertain') LIMIT 1""", (account, order_key)).fetchone() is not None

    def record(self, plan, status, detail):
        with self.db:
            self.db.execute("""INSERT INTO operations VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(order_key) DO UPDATE SET status=excluded.status,
                detail=excluded.detail, updated=excluded.updated""", (
                plan.operation_key, plan.order.number, plan.workflow.product,
                plan.order.arrival, plan.target.isoformat(), status, detail,
                datetime.now(timezone.utc).isoformat()))

    def export(self, path):
        rows = self.db.execute("""SELECT o.order_number,o.product,o.arrival,o.eta,o.status,o.detail,o.updated,
            COALESCE(a.account,''),COALESCE(a.before_json,''),COALESCE(a.comment,''),
            COALESCE(a.reason,''),COALESCE(a.policy,'ground')
            FROM operations o LEFT JOIN sla_audit a ON o.order_key=a.operation_key ORDER BY o.updated DESC""").fetchall()
        with open(path, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Order", "Product", "Arrival", "ETA (Eastern)", "Status", "Detail", "Updated (UTC)",
                             "Account", "Previous ETA and source", "Saved comment", "Reason", "Policy"])
            for row in rows:
                writer.writerow([("'" + s) if s.startswith(("=", "+", "-", "@")) else s for s in map(str, row)])

    def close(self):
        self.db.close()

    def import_history(self, path):
        """Merge an old journal atomically. Conflicting evidence requires review."""
        try:
            with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as old:
                if old.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise NeedsAttention("The selected history file is damaged.")
                operations = old.execute("SELECT order_key,order_number,product,arrival,eta,status,detail,updated FROM operations").fetchall()
                has_audit = old.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sla_audit'").fetchone()
                audit = old.execute("SELECT operation_key,account,order_key,before_json,comment,reason,policy FROM sla_audit").fetchall() if has_audit else []
            added = 0
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                for table, rows in (("operations", operations), ("sla_audit", audit)):
                    key = "order_key" if table == "operations" else "operation_key"
                    for row in rows:
                        current = self.db.execute(f"SELECT * FROM {table} WHERE {key}=?", (row[0],)).fetchone()
                        if current is not None and current != row:
                            raise NeedsAttention("The histories contain conflicting records. Nothing was imported; review them before merging.")
                        if current is None:
                            self.db.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in row)})", row)
                            added += table == "operations"
            return added
        except sqlite3.Error as exc:
            raise NeedsAttention("This is not a readable TitleVision history database.") from exc

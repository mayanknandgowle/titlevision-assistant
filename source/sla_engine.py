"""SLA preview and verified edit orchestration, isolated from Ground rules."""
from dataclasses import replace
from datetime import datetime

from engine import Engine, PreviewRow
from rules import EASTERN, NeedsAttention, Stopped, match_workflow, plan_is_current, saved_exactly
from sla import make_sla_plan, unchanged_sla_plan, same_sla_task


class SLAEngine(Engine):
    def preview(self):
        self.check_stop()
        account, orders = self.site.read_sla_queue()
        self.emit("account", account)
        grouped = {}
        for order in orders:
            grouped.setdefault(order.key, []).append(order)
        self.emit("sla_summary", {"total": len(grouped)})
        output = []
        for index, items in enumerate(grouped.values()):
            self.check_stop()
            order = items[0]
            self.emit("progress", (index, len(grouped), "Checking SLA for " + order.number))
            try:
                if any(item != order for item in items):
                    raise NeedsAttention("Duplicate task rows disagree. Review this product manually.")
                if self.journal.pending_sla(account, order.key):
                    raise NeedsAttention("A previous SLA save is uncertain. Check TitleVision before retrying.")
                workflows, reminders = self.site.inspect(order, account)
                plan = make_sla_plan(order, match_workflow(order, workflows), reminders, account)
                if self.journal.get(plan.operation_key):
                    raise NeedsAttention("This ETA revision has already been attempted. Check update history.")
                action = "Edit existing ETA" if plan.old_reminder else "Add missing ETA"
                row = PreviewRow(order, "Confirm reason", action + "; five weekdays from " +
                                 plan.base_eta[:10] + ". Select this row and confirm its actual delay reason.", plan)
            except NeedsAttention as exc:
                row = PreviewRow(order, "Needs review", str(exc))
            output.append(row)
            self.emit("row", row)
        self.emit("progress", (len(grouped), len(grouped), "Preview complete. Confirm the reason for each ETA to update."))
        return output

    def apply(self, rows):
        plans = [r.plan for r in rows if r.status == "Ready" and r.plan and r.plan.approved]
        counts = {"saved": 0, "skipped": 0, "review": 0}
        for index, plan in enumerate(plans):
            self.check_stop()
            self.emit("progress", (index, len(plans), "Rechecking " + plan.order.number))
            if not plan_is_current(plan):
                raise NeedsAttention("The preview expired. Preview and confirm the delay reasons again.")
            if self.journal.pending_sla(plan.account, plan.order.key):
                raise NeedsAttention("An uncertain SLA save blocks this order until it has been reviewed.")
            if self.journal.get(plan.operation_key):
                self.emit("result", (plan.order.key, "Skipped", "This ETA revision is already recorded."))
                counts["skipped"] += 1
                continue
            try:
                account, orders = self.site.read_sla_queue()
                if account != plan.account:
                    raise NeedsAttention("The signed-in account changed. Preview again.")
                matching = [o for o in orders if o.key == plan.order.key]
                if not matching or any(not same_sla_task(plan.order, o) for o in matching):
                    raise NeedsAttention("The task, SLA, geography, client, or ETA comment changed since preview.")
                workflows, reminders = self.site.inspect(matching[0], account)
                fresh = make_sla_plan(matching[0], match_workflow(matching[0], workflows), reminders, account)
                if not unchanged_sla_plan(plan, fresh):
                    raise NeedsAttention("The product or existing ETA changed. Preview again.")
                live = replace(fresh, reason=plan.reason, reason_source=plan.reason_source,
                               approved=True, scanned_at=plan.scanned_at)
                self.site.prepare(live)
                if self.stop.is_set():
                    self.site.cancel_form()
                    raise Stopped()
                if not plan_is_current(live):
                    self.site.cancel_form()
                    raise NeedsAttention("The preview expired while preparing the ETA form.")
            except NeedsAttention as exc:
                self.site.cancel_form()
                self.emit("result", (plan.order.key, "Needs review", str(exc)))
                counts["review"] += 1
                continue
            if not self.journal.reserve(live):
                self.site.cancel_form()
                self.emit("result", (plan.order.key, "Skipped", "Another app already reserved this ETA revision."))
                counts["skipped"] += 1
                continue
            try:
                self.site.submit()
                verified = self.site.wait_saved(live)
            except Exception:
                try:
                    verified = saved_exactly(self.site.reminders(), live)
                except Exception:
                    verified = False
            if not verified:
                self.journal.record(live, "uncertain", "SLA edit was not confirmed. No automatic retry.")
                self.emit("result", (plan.order.key, "Needs review", "Save uncertain. Check the existing ETA in TitleVision."))
                raise NeedsAttention("Stopped because the SLA update could not be verified for " + plan.order.number)
            self.journal.record(live, "saved", "Verified revised ETA, comment, and related product.")
            self.emit("result", (plan.order.key, "Saved", "Revised ETA and delay comment verified."))
            counts["saved"] += 1
        self.emit("progress", (len(plans), len(plans), "SLA updates finished."))
        return counts

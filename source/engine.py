"""Preview/revalidate/commit orchestration; independent of the GUI."""
from datetime import datetime
from dataclasses import dataclass
import threading

from rules import (EASTERN, NeedsAttention, Plan, Stopped, eta_target,
                   match_workflow, matching_reminders, plan_is_current, saved_exactly)


@dataclass
class PreviewRow:
    order: object
    status: str
    detail: str
    plan: object = None


class Engine:
    def __init__(self, site, journal, emit, stop=None):
        self.site, self.journal, self.emit = site, journal, emit
        self.stop = stop or threading.Event()
        self.site.check_stop = self.check_stop

    def check_stop(self):
        if self.stop.is_set():
            raise Stopped()

    def preview(self):
        self.check_stop()
        account, orders = self.site.read_queue()
        grouped = {}
        for order in orders:
            grouped.setdefault(order.key, []).append(order)
        candidates = [items[0] for items in grouped.values() if not any(o.eta_comment.strip() for o in items)]
        self.emit("account", account)
        self.emit("summary", {"total": len(grouped), "candidates": len(candidates),
                              "existing": len(grouped) - len(candidates)})
        output = []
        for index, order in enumerate(candidates):
            self.check_stop()
            self.emit("progress", (index, len(candidates), "Reading " + order.number))
            previous = self.journal.get(order.key)
            if previous:
                status = "Already saved" if previous[0] == "saved" else "Needs review"
                row = PreviewRow(order, status, "A previous update is recorded: " + previous[0] + ". Check TitleVision before any manual change.")
            else:
                try:
                    workflows, reminders = self.site.inspect(order, account)
                    workflow = match_workflow(order, workflows)
                    now = datetime.now(EASTERN)
                    plan = Plan(order, workflow, eta_target(workflow.sla, now), account, now)
                    if matching_reminders(reminders, plan.related):
                        row = PreviewRow(order, "Skipped", "An ETA already exists for this product.")
                    elif not workflow.alarm_id:
                        row = PreviewRow(order, "Needs review", "This product has no alarm button.")
                    else:
                        row = PreviewRow(order, "Ready", "SLA/NB date at 5 PM Eastern", plan)
                except NeedsAttention as exc:
                    row = PreviewRow(order, "Needs review", str(exc))
            output.append(row)
            self.emit("row", row)
        self.emit("progress", (len(candidates), len(candidates), "Preview complete. No orders have been changed."))
        return output

    def apply(self, rows):
        plans = [r.plan for r in rows if r.status == "Ready" and r.plan]
        counts = {"saved": 0, "skipped": 0, "review": 0}
        for index, plan in enumerate(plans):
            self.check_stop()
            self.emit("progress", (index, len(plans), "Checking " + plan.order.number))
            if not plan_is_current(plan):
                raise NeedsAttention("The preview is more than 30 minutes old, or an ETA has passed. Preview orders again.")
            if self.journal.get(plan.order.key):
                self.emit("result", (plan.order.key, "Skipped", "An earlier attempt is recorded; no duplicate submission."))
                counts["skipped"] += 1
                continue
            # Re-read the queue immediately before each order, including comments changed by other users.
            account, current_orders = self.site.read_queue()
            if account != plan.account:
                raise NeedsAttention("The account changed after preview. Preview again before updating.")
            current = [o for o in current_orders if o.key == plan.order.key]
            if not current or any(o.eta_comment.strip() for o in current):
                self.emit("result", (plan.order.key, "Skipped", "This order left the queue or now has ETA comments."))
                counts["skipped"] += 1
                continue
            workflows, reminders = self.site.inspect(plan.order, plan.account)
            workflow = match_workflow(plan.order, workflows)
            target = eta_target(workflow.sla)
            if (workflow.external_id != plan.workflow.external_id or target != plan.target
                    or workflow.product != plan.workflow.product):
                self.emit("result", (plan.order.key, "Needs review", "The product or SLA/NB date changed. Preview again."))
                counts["review"] += 1
                continue
            if matching_reminders(reminders, plan.related):
                self.emit("result", (plan.order.key, "Skipped", "An ETA already exists for this product."))
                counts["skipped"] += 1
                continue
            # Use the freshly observed alarm element; row indices can change between page visits.
            live = Plan(plan.order, workflow, target, plan.account, plan.scanned_at)
            self.site.prepare(live)
            if self.stop.is_set():
                self.site.cancel_form()
                raise Stopped()
            if not plan_is_current(live):
                self.site.cancel_form()
                raise NeedsAttention("The ETA or preview expired while preparing the form. Preview again.")
            if not self.journal.reserve(live):
                self.site.cancel_form()
                self.emit("result", (plan.order.key, "Skipped", "Another app instance already reserved this update."))
                counts["skipped"] += 1
                continue
            # After this point, finish verification even when Stop was requested.
            try:
                self.site.submit()
                verified = self.site.wait_saved(live)
            except Exception:
                try:
                    verified = saved_exactly(self.site.reminders(), live)
                except Exception:
                    verified = False
            if not verified:
                self.journal.record(live, "uncertain", "Save was not confirmed. Check the order in TitleVision; no retry was made.")
                self.emit("result", (plan.order.key, "Needs review", "Save not confirmed. Check TitleVision before retrying."))
                raise NeedsAttention("Stopped because a save could not be confirmed for " + plan.order.number + ". No duplicate submission was attempted.")
            self.journal.record(live, "saved", "Verified ETA date, 5 PM Eastern, comment, and related product.")
            self.emit("result", (plan.order.key, "Saved", "ETA and comment verified in TitleVision."))
            counts["saved"] += 1
        self.emit("progress", (len(plans), len(plans), "Updates finished."))
        return counts

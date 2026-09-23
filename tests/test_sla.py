from dataclasses import replace
from datetime import datetime, timedelta, date
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from rules import EASTERN, Order, Workflow, Plan, NeedsAttention, Stopped, saved_exactly
from sla import (REASONS, approve_reason, five_workdays, make_sla_plan, policy_reason,
                 reason_suggestion, unchanged_sla_plan)
from sla_engine import SLAEngine
from journal import Journal

NOW = datetime(2026, 9, 23, 10, tzinfo=EASTERN)


class SLAFakeSite:
    def __init__(self, now=NOW):
        yesterday = (now - timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
        self.order = Order("TPS-SLA-001", "Full Title", "09/10/2026 10:20 AM",
                           "https://tv.datatracetitle.com/OrderOverview.aspx?PublicOrderId=11111111-1111-1111-1111-111111111111",
                           "Prior search required", "Online", "NJ", "Passaic", "TELSIX", "Available", "Expired")
        self.workflow = Workflow("Full Title", "P-001", self.order.arrival,
                                 yesterday.strftime("%m/%d/%Y 01:00 PM [NB]"), "alarm1")
        self.account = "Tester"
        self.orders = [self.order]
        related = Plan(self.order, self.workflow, now, self.account, now).related
        self.entries = [{"due": yesterday.strftime("%m/%d/%Y %I:%M %p"),
                         "description": "(ETA) ETA: Additional records prior to the owner policy are required for the 60-year search. The ETA is 09/22 EOD.",
                         "related": related, "edit_id": "edit1", "edit_href": "#edit"}]
        self.clicks = 0
        self.confirm_save = True
        self.raise_after_commit = False
        self.stop_at_prepare = None
        self.cancelled = False
        self.plan = None

    def read_sla_queue(self):
        return self.account, self.orders

    def inspect(self, order, account):
        return [self.workflow], self.entries

    def prepare(self, plan):
        self.plan = plan
        if self.stop_at_prepare:
            self.stop_at_prepare.set()

    def cancel_form(self):
        self.cancelled = True

    def submit(self):
        self.clicks += 1
        if self.confirm_save:
            self.entries = [{"due": self.plan.target.strftime("%m/%d/%Y %I:%M %p"),
                             "description": "(ETA) " + self.plan.comment, "related": self.plan.related,
                             "edit_id": "edit1", "edit_href": "#edit"}]
        if self.raise_after_commit:
            raise TimeoutError()

    def wait_saved(self, plan):
        return saved_exactly(self.entries, plan)

    def reminders(self):
        return self.entries


class SLARulesTests(unittest.TestCase):
    def setUp(self):
        self.site = SLAFakeSite()

    def plan(self):
        s = self.site
        return make_sla_plan(s.order, s.workflow, s.entries, s.account, NOW)

    def test_example_uses_existing_eta_not_sla(self):
        self.site.workflow = replace(self.site.workflow, sla="09/16/2026 12:01 PM [NB]")
        self.assertEqual(self.plan().target, datetime(2026, 9, 29, 17, tzinfo=EASTERN))

    def test_weekend_start_excluded(self):
        self.assertEqual(five_workdays(datetime(2026, 9, 26, 17, tzinfo=EASTERN)).date(), date(2026, 10, 2))

    def test_year_boundary_and_dst(self):
        self.assertEqual(five_workdays(datetime(2026, 12, 31, 17, tzinfo=EASTERN)).date(), date(2027, 1, 7))
        self.assertEqual(five_workdays(datetime(2026, 10, 30, 17, tzinfo=EASTERN)).utcoffset(), timedelta(hours=-5))

    def test_explicit_holiday_calendar(self):
        self.assertEqual(five_workdays(NOW, {date(2026, 9, 24)}).date(), date(2026, 10, 1))

    def test_all_twenty_reasons_render_without_placeholders(self):
        self.assertEqual(len(REASONS), 20)
        for reason in REASONS:
            with self.subTest(reason=reason):
                p = approve_reason(self.plan(), reason)
                self.assertNotIn("[MM/DD]", p.comment)
                self.assertIn("09/29", p.comment)
                self.assertTrue(p.approved)

    def test_spreadsheet_state_client_matrix(self):
        expected = [("MD", "TELSIX", "Judgment copies pending"),
                    ("PA", "ANY", "Prothonotary results pending")]
        expected += [(state, "VYLLAMMP", "Attorney opinion pending") for state in ("SC", "LA", "NC", "WV", "GA")]
        for state, client, reason in expected:
            order = replace(self.site.order, state=state, client=client)
            self.assertEqual(policy_reason(order), reason)
            p = approve_reason(replace(self.plan(), order=order), reason)
            self.assertIn("09/29 EOB", p.comment)
        self.assertEqual(policy_reason(replace(self.site.order, state="MD", client="OTHER")), "")

    def test_existing_context_suggested_but_not_approved(self):
        p = self.plan()
        self.assertEqual(p.reason, "Complex or historical search")
        self.assertFalse(p.approved)

    def test_ambiguous_reason_requires_selection(self):
        reason, source = reason_suggestion(self.site.order, "Attorney opinion and judgment copies are pending")
        self.assertEqual(reason, "")

    def test_missing_eta_uses_sla(self):
        self.site.entries = []
        self.site.order = replace(self.site.order, eta_comment="")
        self.assertFalse(self.plan().old_reminder)
        self.assertEqual(self.plan().target.day, 29)

    def test_queue_eta_cannot_be_silently_replaced_with_new_reminder(self):
        self.site.entries = []
        with self.assertRaisesRegex(NeedsAttention, "no matching product ETA"):
            self.plan()

    def test_empty_and_nontruncated_partial_product_names_rejected(self):
        from rules import match_workflow
        for name in ("", "Full"):
            with self.assertRaises(NeedsAttention):
                match_workflow(replace(self.site.order, product=name), [self.site.workflow])

    def test_future_eta_is_not_extended_again(self):
        self.site.entries[0]["due"] = "09/29/2026 05:00 PM"
        with self.assertRaisesRegex(NeedsAttention, "future ETA"):
            self.plan()

    def test_already_stale_target_is_blocked(self):
        self.site.entries[0]["due"] = "09/01/2026 05:00 PM"
        with self.assertRaisesRegex(NeedsAttention, "still in the past"):
            self.plan()

    def test_ineligible_status_and_suspended_product(self):
        self.site.order = replace(self.site.order, task_status="Completed")
        with self.assertRaises(NeedsAttention):
            self.plan()
        self.site.order = replace(self.site.order, task_status="Available")
        self.site.workflow = replace(self.site.workflow, suspended="09/22/2026")
        with self.assertRaises(NeedsAttention):
            self.plan()

    def test_unexpired_sla_is_blocked(self):
        self.site.workflow = replace(self.site.workflow, sla="09/30/2026 01:00 PM [NB]")
        with self.assertRaisesRegex(NeedsAttention, "has not expired"):
            self.plan()

    def test_missing_edit_and_multiple_reminders_are_blocked(self):
        old = self.site.entries[0].copy()
        self.site.entries[0].update(edit_id="", edit_href="")
        with self.assertRaisesRegex(NeedsAttention, "Edit"):
            self.plan()
        self.site.entries = [old, old.copy()]
        with self.assertRaisesRegex(NeedsAttention, "Multiple"):
            self.plan()

    def test_operation_identity_is_stable_across_reason_changes(self):
        p = self.plan()
        self.assertEqual(p.operation_key, approve_reason(p, "Tax information pending").operation_key)
        self.assertNotEqual(p.operation_key, replace(p, account="SomeoneElse").operation_key)

    def test_edit_verification_rejects_duplicate_append(self):
        p = approve_reason(self.plan(), "Complex or historical search")
        new = {"due": "09/29/2026 05:00 PM", "description": "(ETA) " + p.comment, "related": p.related}
        self.assertTrue(saved_exactly([new], p))
        self.assertFalse(saved_exactly(self.site.entries + [new], p))
        new["due"] = "9/29/2026 5:00 PM"
        self.assertTrue(saved_exactly([new], p))


class SLAEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "history.sqlite3"
        self.journal = Journal(self.path)
        self.site = SLAFakeSite(datetime.now(EASTERN))
        self.events = []
        self.stop = threading.Event()
        self.engine = SLAEngine(self.site, self.journal, lambda *v: self.events.append(v), self.stop)

    def tearDown(self):
        self.journal.close()
        self.temp.cleanup()

    def ready(self):
        rows = self.engine.preview()
        self.assertEqual(rows[0].status, "Confirm reason")
        rows[0].plan = approve_reason(rows[0].plan, "Complex or historical search")
        rows[0].status = "Ready"
        return rows

    def test_preview_requires_reason_and_never_saves(self):
        rows = self.engine.preview()
        self.assertEqual(rows[0].status, "Confirm reason")
        self.engine.apply(rows)
        self.assertEqual(self.site.clicks, 0)

    def test_verified_edit_audit_and_rerun(self):
        rows = self.ready()
        self.assertEqual(self.engine.apply(rows)["saved"], 1)
        self.assertEqual(len(self.site.entries), 1)
        self.engine.apply(rows)
        self.assertEqual(self.site.clicks, 1)
        stored = self.journal.db.execute("SELECT before_json,comment,reason FROM sla_audit").fetchone()
        self.assertIn("60-year", stored[0])
        self.assertEqual(stored[1], rows[0].plan.comment)
        self.assertEqual(self.engine.preview()[0].status, "Needs review")

    def test_changed_reminder_blocks_save(self):
        rows = self.ready()
        self.site.entries[0]["description"] = "(ETA) Changed by another user"
        self.assertEqual(self.engine.apply(rows)["review"], 1)
        self.assertEqual(self.site.clicks, 0)

    def test_changed_client_or_task_blocks_save(self):
        rows = self.ready()
        self.site.orders = [replace(self.site.order, client="CHANGED")]
        self.assertEqual(self.engine.apply(rows)["review"], 1)
        self.assertEqual(self.site.clicks, 0)

    def test_uncertain_save_blocks_new_reason_and_restart(self):
        rows = self.ready()
        self.site.confirm_save = False
        with self.assertRaises(NeedsAttention):
            self.engine.apply(rows)
        self.assertEqual(self.journal.get(rows[0].plan.operation_key)[0], "uncertain")
        self.journal.close()
        self.journal = Journal(self.path)
        self.engine.journal = self.journal
        self.assertEqual(self.engine.preview()[0].status, "Needs review")
        self.assertEqual(self.site.clicks, 1)

    def test_timeout_after_success_is_verified_without_retry(self):
        rows = self.ready()
        self.site.raise_after_commit = True
        self.assertEqual(self.engine.apply(rows)["saved"], 1)
        self.assertEqual(self.site.clicks, 1)

    def test_stop_before_commit_cancels(self):
        rows = self.ready()
        self.site.stop_at_prepare = self.stop
        with self.assertRaises(Stopped):
            self.engine.apply(rows)
        self.assertEqual(self.site.clicks, 0)
        self.assertTrue(self.site.cancelled)

    def test_different_task_rows_for_same_product_are_not_silently_collapsed(self):
        self.site.orders.append(replace(self.site.order, task_status="Active"))
        self.assertEqual(self.engine.preview()[0].status, "Needs review")

    def test_stale_preview_blocks(self):
        rows = self.ready()
        rows[0].plan = replace(rows[0].plan, scanned_at=datetime.now(EASTERN) - timedelta(hours=1))
        with self.assertRaises(NeedsAttention):
            self.engine.apply(rows)
        self.assertEqual(self.site.clicks, 0)

    def test_pending_revision_blocks_competing_reservation(self):
        p = self.ready()[0].plan
        other = Journal(self.path)
        try:
            self.assertTrue(self.journal.reserve(p))
            self.assertFalse(other.reserve(replace(p, old_reminder=("changed",))))
        finally:
            other.close()

    def test_a_later_legitimate_revision_has_separate_history(self):
        p = self.ready()[0].plan
        self.assertTrue(self.journal.reserve(p))
        self.journal.record(p, "saved", "Verified")
        later = replace(p, base_eta=p.target.isoformat(), target=p.target + timedelta(days=7))
        self.assertTrue(self.journal.reserve(later))
        self.assertEqual(self.journal.db.execute("SELECT COUNT(*) FROM sla_audit").fetchone()[0], 2)

    def test_history_export_has_previous_and_new_comment(self):
        rows = self.ready()
        self.engine.apply(rows)
        output = Path(self.temp.name) / "audit.csv"
        self.journal.export(output)
        contents = output.read_text(encoding="utf-8-sig")
        self.assertIn("60-year", contents)
        self.assertIn(rows[0].plan.comment, contents)


if __name__ == "__main__":
    unittest.main()

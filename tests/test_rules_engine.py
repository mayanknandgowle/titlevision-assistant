from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from engine import Engine
from journal import Journal
from rules import *


class FakeSite:
    def __init__(self):
        self.account = "TestAccount"
        self.order = Order("TPS-DEMO-001", "Full Title", "09/17/2026 10:11 AM", BASE_URL + "OrderOverview.aspx?PublicOrderId=11111111-1111-1111-1111-111111111111")
        day = (datetime.now(EASTERN) + timedelta(days=5)).strftime("%m/%d/%Y")
        self.workflow = Workflow("Full Title", "PRODUCT-001", "9/17/2026 10:11:29 AM", day + " 01:00 PM [NB]", "alarm1")
        self.orders = [self.order]
        self.entries = []
        self.clicks = 0
        self.prepared = 0
        self.confirm_save = True
        self.raise_after_commit = False
        self.stop_at_prepare = None
        self.cancelled = False

    def read_queue(self):
        return self.account, self.orders

    def inspect(self, order, account):
        return [self.workflow], self.entries

    def prepare(self, plan):
        self.prepared += 1
        self.plan = plan
        if self.stop_at_prepare:
            self.stop_at_prepare.set()

    def submit(self):
        self.clicks += 1
        if self.confirm_save:
            self.entries.append({"due": self.plan.target.strftime("%m/%d/%Y %I:%M %p"),
                                 "description": "(ETA) " + COMMENT, "related": self.plan.related})
        if self.raise_after_commit:
            raise TimeoutError()

    def wait_saved(self, plan):
        return saved_exactly(self.entries, plan)

    def reminders(self):
        return self.entries

    def cancel_form(self):
        self.cancelled = True


class RulesTests(unittest.TestCase):
    def test_exact_comment(self):
        self.assertEqual(COMMENT, "Hello, Order has been assigned to the abstractor, and we will ensure completion within SLA")

    def test_eastern_date_not_machine_timezone(self):
        now = datetime(2026, 9, 22, 16, 59, tzinfo=EASTERN)
        self.assertEqual(eta_target("09/22/2026 08:00 AM [NB]", now).hour, 17)
        self.assertEqual(eta_target("09/23/2026 01:00 PM [NB]", now).utcoffset(), timedelta(hours=-4))

    def test_past_eta_rejected_without_date_adjustment(self):
        with self.assertRaises(NeedsAttention):
            eta_target("09/22/2026 01:00 PM [NB]", datetime(2026, 9, 22, 17, tzinfo=EASTERN))

    def test_weekend_sla_preserved_for_ground_workflow(self):
        target = eta_target("09/26/2026 09:00 AM [NB]", datetime(2026, 9, 22, tzinfo=EASTERN))
        self.assertEqual(target.day, 26)

    def test_dst_standard_time(self):
        target = eta_target("12/01/2026 10:00 AM [NB]", datetime(2026, 9, 22, tzinfo=EASTERN))
        self.assertEqual(target.utcoffset(), timedelta(hours=-5))

    def test_bad_dates(self):
        for value in ("", "4d 2h", "02/31/2026 01:00 PM"):
            with self.assertRaises(NeedsAttention):
                eta_target(value)

    def test_link_destination_validation(self):
        suffix = "OrderOverview.aspx?PublicOrderId=11111111-1111-1111-1111-111111111111"
        self.assertEqual(order_url(suffix), BASE_URL + suffix)
        for href in ("https://example.com/" + suffix, "javascript:alert(1)", "/Logout.aspx", "http://tv.datatracetitle.com/" + suffix):
            with self.assertRaises(NeedsAttention):
                order_url(href)

    def test_match_current_product_and_arrival(self):
        site = FakeSite()
        historical = replace(site.workflow, completed="9/18/2026 12:00 PM")
        self.assertEqual(match_workflow(site.order, [historical, site.workflow]), site.workflow)
        with self.assertRaises(NeedsAttention):
            match_workflow(site.order, [site.workflow, site.workflow])
        with self.assertRaises(NeedsAttention):
            match_workflow(site.order, [replace(site.workflow, product="Current Owner")])

    def test_truncated_product(self):
        site = FakeSite()
        self.assertEqual(match_workflow(replace(site.order, product="Full Ti.."), [site.workflow]), site.workflow)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "history.sqlite3"
        self.journal = Journal(self.path)
        self.site = FakeSite()
        self.events = []
        self.stop = threading.Event()
        self.engine = Engine(self.site, self.journal, lambda *args: self.events.append(args), self.stop)

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def test_preview_never_submits(self):
        rows = self.engine.preview()
        self.assertEqual(rows[0].status, "Ready")
        self.assertEqual(self.site.prepared, 0)
        self.assertEqual(self.site.clicks, 0)

    def test_nonblank_queue_comments_preserved(self):
        self.site.orders = [replace(self.site.order, eta_comment="Existing comment")]
        self.assertEqual(self.engine.preview(), [])

    def test_duplicate_task_rows_collapse(self):
        self.site.orders = [self.site.order, self.site.order]
        self.assertEqual(len(self.engine.preview()), 1)

    def test_duplicate_task_nonblank_wins(self):
        self.site.orders = [self.site.order, replace(self.site.order, eta_comment="Already set")]
        self.assertEqual(self.engine.preview(), [])

    def test_success_and_rerun_has_no_duplicate(self):
        rows = self.engine.preview()
        self.assertEqual(self.engine.apply(rows)["saved"], 1)
        self.assertEqual(self.engine.apply(rows)["skipped"], 1)
        self.assertEqual(self.site.clicks, 1)
        self.assertEqual(self.journal.get(self.site.order.key)[0], "saved")

    def test_changed_comment_skipped_after_preview(self):
        rows = self.engine.preview()
        self.site.orders = [replace(self.site.order, eta_comment="Another user updated this")]
        self.assertEqual(self.engine.apply(rows)["skipped"], 1)
        self.assertEqual(self.site.clicks, 0)

    def test_removed_order_skipped(self):
        rows = self.engine.preview()
        self.site.orders = []
        self.assertEqual(self.engine.apply(rows)["skipped"], 1)

    def test_changed_sla_needs_review(self):
        rows = self.engine.preview()
        new_day = (datetime.now(EASTERN) + timedelta(days=6)).strftime("%m/%d/%Y")
        self.site.workflow = replace(self.site.workflow, sla=new_day + " 01:00 PM [NB]")
        self.assertEqual(self.engine.apply(rows)["review"], 1)
        self.assertEqual(self.site.clicks, 0)

    def test_existing_overview_eta_preserved(self):
        rows = self.engine.preview()
        self.site.entries = [{"due": "01/01/2030 05:00 PM", "description": "(ETA) Existing", "related": rows[0].plan.related}]
        self.assertEqual(self.engine.apply(rows)["skipped"], 1)
        self.assertEqual(self.engine.preview()[0].status, "Skipped")

    def test_historical_eta_does_not_block_active_product(self):
        self.site.entries = [{"due": "01/01/2026 05:00 PM", "description": "(ETA) Historical", "related": "Full Title (01/01/2026 10:11 AM)"}]
        self.assertEqual(self.engine.preview()[0].status, "Ready")

    def test_expired_preview(self):
        rows = self.engine.preview()
        rows[0].plan = replace(rows[0].plan, scanned_at=datetime.now(EASTERN) - timedelta(minutes=31))
        with self.assertRaises(NeedsAttention):
            self.engine.apply(rows)
        self.assertEqual(self.site.clicks, 0)

    def test_account_changed(self):
        rows = self.engine.preview()
        self.site.account = "OtherAccount"
        with self.assertRaises(NeedsAttention):
            self.engine.apply(rows)
        self.assertEqual(self.site.clicks, 0)

    def test_stop_before_submit(self):
        rows = self.engine.preview()
        self.site.stop_at_prepare = self.stop
        with self.assertRaises(Stopped):
            self.engine.apply(rows)
        self.assertTrue(self.site.cancelled)
        self.assertEqual(self.site.clicks, 0)
        self.assertIsNone(self.journal.get(self.site.order.key))

    def test_unconfirmed_save_stops_and_blocks_retry(self):
        rows = self.engine.preview()
        self.site.confirm_save = False
        with self.assertRaises(NeedsAttention):
            self.engine.apply(rows)
        self.assertEqual(self.site.clicks, 1)
        self.assertEqual(self.journal.get(self.site.order.key)[0], "uncertain")
        self.assertEqual(self.engine.preview()[0].status, "Needs review")
        self.engine.apply(rows)
        self.assertEqual(self.site.clicks, 1)

    def test_timeout_after_success_does_not_click_twice(self):
        rows = self.engine.preview()
        self.site.raise_after_commit = True
        self.assertEqual(self.engine.apply(rows)["saved"], 1)
        self.assertEqual(self.site.clicks, 1)

    def test_atomic_reservation_across_app_instances(self):
        plan = self.engine.preview()[0].plan
        second = Journal(self.path)
        try:
            self.assertTrue(self.journal.reserve(plan))
            self.assertFalse(second.reserve(plan))
            self.assertEqual(second.get(plan.order.key)[0], "submitting")
        finally:
            second.close()

    def test_export(self):
        self.engine.apply(self.engine.preview())
        path = Path(self.tmp.name) / "history.csv"
        self.journal.export(path)
        contents = path.read_text(encoding="utf-8-sig")
        self.assertIn("TPS-DEMO-001", contents)
        self.assertIn("saved", contents)
        self.assertNotIn("password", contents)


if __name__ == "__main__":
    unittest.main()

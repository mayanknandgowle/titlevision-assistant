"""Offline browser contract tests: every network request is intercepted."""
from dataclasses import replace
from datetime import datetime, timedelta
import html
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from playwright.sync_api import sync_playwright
from rules import EASTERN, QUEUE_URL, NeedsAttention, match_workflow, saved_exactly
from sla import approve_reason, make_sla_plan, unchanged_sla_plan
from titlevision import TitleVision
from test_browser_adapter import queue_html, overview_html, cells, QID, WID, RID, PID, DID


NAV = '<a href="Queues.aspx?qid=99999">All Active and Available Tasks*</a>'


class SLABrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch(channel="msedge", headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.qhtml = queue_html(comment="The old ETA") + NAV
        self.ohtml = overview_html()
        future = (datetime.now(EASTERN) + timedelta(days=5)).strftime("%m/%d/%Y")
        self.old_due = (datetime.now(EASTERN) - timedelta(days=1)).strftime("%m/%d/%Y") + " 05:00 PM"
        self.ohtml = self.ohtml.replace(future + " 01:00 PM [NB]", self.old_due.split()[0] + " 01:00 PM [NB]")
        self.old_comment = "ETA: The attorney opinion certificate remains pending."
        row = cells([self.old_due.replace(" ", "\n", 1), "", "", "(ETA) " + self.old_comment, "No",
                     "Full Title (09/17/2026 10:11 AM)", "TestAccount", "today"])
        edit = '<td><a id="edit1" href="#" onclick="editForm();return false">Edit</a></td>'
        existing = '<table id="existing"><tr>' + row + edit + '</tr></table>'
        self.ohtml = self.ohtml.replace("You have no reminders set.", existing)
        script = "<script>function editForm(){document.getElementById('date').value=" + json.dumps(self.old_due) + ";document.getElementById('" + DID + "').value=" + json.dumps(self.old_comment) + ";openForm();}</script>"
        self.ohtml += script
        self.ohtml = self.ohtml.replace('onclick="save()">Add</button>', 'onclick="save()">Add Reminder</button>')
        self.urls = []
        self.context.route("**/*", self.route)
        self.site = TitleVision(headless=True)
        self.site.context = self.context
        self.site.queue_page = self.context.new_page()
        self.site.detail_page = self.context.new_page()
        self.site.queue_page.goto(QUEUE_URL)

    def route(self, route):
        self.urls.append(route.request.url)
        route.fulfill(status=200, content_type="text/html", body=self.qhtml if "Queues.aspx" in route.request.url else self.ohtml)

    def tearDown(self):
        self.context.close()

    def plan(self):
        account, orders = self.site.read_sla_queue()
        workflows, reminders = self.site.inspect(orders[0], account)
        p = make_sla_plan(orders[0], match_workflow(orders[0], workflows), reminders, account)
        return approve_reason(p, "Attorney opinion pending")

    def test_discovers_active_queue_and_reads_state_client_status(self):
        account, orders = self.site.read_sla_queue()
        self.assertEqual(self.site.sla_queue_url, "https://tv.datatracetitle.com/Queues.aspx?qid=99999")
        self.assertEqual(orders[0].task_status, "Available")
        self.assertEqual(orders[0].state, "VA")
        self.assertEqual(orders[0].client, "DEMO")

    def test_online_orders_are_included_in_sla_mode(self):
        self.qhtml = self.qhtml.replace("<td>Ground</td>", "<td>Online</td>")
        self.assertEqual(self.site.read_sla_queue()[1][0].mode, "Online")

    def test_edit_existing_eta_and_verify_single_replacement(self):
        p = self.plan()
        self.assertEqual(p.reason, "Attorney opinion pending")
        self.site.prepare(p)
        self.site.submit()
        self.assertTrue(self.site.wait_saved(p, timeout=4))
        self.assertEqual(len(self.site.reminders()), 1)
        self.assertEqual(self.site.reminders()[0]["description"], "(ETA) " + p.comment)

    def test_wrong_edit_form_is_rejected(self):
        self.ohtml = self.ohtml.replace(json.dumps(self.old_comment), json.dumps("Someone else's reminder"))
        with self.assertRaisesRegex(NeedsAttention, "Edit form does not match"):
            self.site.prepare(self.plan())

    def test_no_named_queue_never_falls_back_to_ground(self):
        self.qhtml = queue_html()
        self.site.queue_page.reload()
        with self.assertRaisesRegex(NeedsAttention, "Ground queue will not"):
            self.site.read_sla_queue()

    def test_changed_sla_headers_rejected(self):
        self.qhtml = self.qhtml.replace("<th>Task Status</th>", "<th>Unknown</th>")
        with self.assertRaisesRegex(NeedsAttention, "columns changed"):
            self.site.read_sla_queue()

    def test_inactive_tasks_excluded(self):
        self.qhtml = self.qhtml.replace("<td>Available</td>", "<td>Completed</td>")
        self.assertEqual(self.site.read_sla_queue()[1], [])

    def test_in_progress_is_active_work(self):
        self.qhtml = self.qhtml.replace("<td>Available</td>", "<td>In Progress</td>")
        self.assertEqual(self.plan().order.task_status, "In Progress")

    def test_elapsed_queue_clock_can_tick_but_product_sla_cannot_change(self):
        p = self.plan()
        fresh = replace(p, order=replace(p.order, sla_expiration="-4d 5h 01m"))
        self.assertTrue(unchanged_sla_plan(p, fresh))
        self.assertFalse(unchanged_sla_plan(p, replace(fresh, workflow=replace(p.workflow, sla="09/01/2026 01:00 PM [NB]"))))

    def test_missing_pagination_control_fails_closed(self):
        self.qhtml = self.qhtml.replace("1 Record(s)", "2 Record(s)")
        with self.assertRaisesRegex(NeedsAttention, "Not all"):
            self.site.read_sla_queue()

    def test_page_change_reads_every_task(self):
        self.qhtml = self.qhtml.replace("1 Record(s)", "2 Record(s)")
        self.qhtml += '<button aria-label="Next Page" onclick="nextPage()">Next Page</button><script>function nextPage(){setTimeout(()=>{document.getElementById(' + json.dumps(QID) + ').innerHTML=document.getElementById(' + json.dumps(QID) + ').innerHTML.replaceAll("TPS-DEMO-001","TPS-DEMO-002");},100);}</script>'
        account, orders = self.site.read_sla_queue()
        self.assertEqual([o.number for o in orders], ["TPS-DEMO-001", "TPS-DEMO-002"])

    def test_duplicate_edit_links_rejected(self):
        self.ohtml = self.ohtml.replace('id="edit1"', 'id="edit1"').replace("</a></td></tr></table>", '</a><a href="#">Edit</a></td></tr></table>', 1)
        with self.assertRaisesRegex(NeedsAttention, "Edit"):
            self.plan()

    def test_partial_unreadable_reminder_list_is_rejected(self):
        extra = '<tr>' + cells(['Unreadable date', '', '', '(ETA) Another ETA', 'No',
                                'Full Title (09/17/2026 10:11 AM)', 'Tester', 'today']) + '</tr>'
        self.ohtml = self.ohtml.replace('<table id="existing">', '<table id="existing">' + extra)
        with self.assertRaisesRegex(NeedsAttention, 'reminder date'):
            self.plan()

    def test_failed_same_url_refresh_is_rejected(self):
        class FailedPage:
            url = QUEUE_URL
            def goto(self, *args, **kwargs):
                raise TimeoutError('refresh failed')
        with self.assertRaisesRegex(NeedsAttention, 'could not be refreshed'):
            self.site._navigate(FailedPage(), QUEUE_URL)


if __name__ == "__main__":
    unittest.main()

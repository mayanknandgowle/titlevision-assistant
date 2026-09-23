"""Browser integration tests. Every request is fulfilled with synthetic HTML.
No credentials are used and no request reaches TitleVision.
"""
from datetime import datetime, timedelta
from pathlib import Path
import html
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from playwright.sync_api import sync_playwright
from rules import *
from titlevision import TitleVision

QID = "ctl00_ContentPlaceHolder1_rdgTaskSummary_ctl00"
WID = "ctl00_ContentPlaceHolder1_grdWorkflowInstances_ctl00"
RID = "ctl00_ContentPlaceHolder1_ucReminders_pnlReminder"
PID = "ctl00_ContentPlaceHolder1_ucReminders_PopupAddEditReminder"
DID = "ctl00_ContentPlaceHolder1_ucReminders_txtDescription"
PUBLIC_ID = "11111111-1111-1111-1111-111111111111"
FOOTER = "<p>You are currently logged in as TestAccount.</p>"


class FakeOpenPage:
    def __init__(self):
        self.url = ""
        self.front = False
        self.closed = False

    def bring_to_front(self):
        self.front = True

    def goto(self, url, wait_until=None):
        self.url = url

    def is_closed(self):
        return self.closed


class FakePersistentContext:
    def __init__(self):
        self.browser = object()
        self.pages = []
        self.closed = False
        self.default_timeout = None
        self.navigation_timeout = None

    def new_page(self):
        page = FakeOpenPage()
        self.pages.append(page)
        return page

    def set_default_timeout(self, value):
        self.default_timeout = value

    def set_default_navigation_timeout(self, value):
        self.navigation_timeout = value

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, context):
        self.context = context
        self.calls = []

    def launch_persistent_context(self, profile, **options):
        self.calls.append((profile, options))
        return self.context


class FakeDriver:
    def __init__(self, context):
        self.chromium = FakeChromium(context)
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakePlaywrightStarter:
    def __init__(self, driver):
        self.driver = driver

    def start(self):
        return self.driver


def cells(values, tag="td"):
    return "".join(f"<{tag}>{html.escape(v)}</{tag}>" for v in values)


def queue_html(count=1, comment="", headers_changed=False):
    headers = ["", "Order Number", "Borrower", "SLA Expiration*", "Orig", "Online/ Ground", "Client", "Product", "Last User", "Skill Grade", "St", "County", "Municipality", "Parcel ID", "Task Name", "Task Status", "Comment", "ETA", "ETA Comments", "Time Since Arrival", "Task Time in Queue", "Arrival Time", "Completed Time", "Vendor", "OPON"]
    if headers_changed:
        headers[18] = "Changed layout"
    row = ["", "TPS-DEMO-001", "", "09/30 01:00 PM", "TPS-AD-", "Ground", "DEMO", "Full Title", "", "0", "VA", "", "", "", "Search", "Available", "", "", comment, "", "", "09/17/2026 10:11 AM", "", "", ""]
    row_html = cells(row)
    row_html = row_html.replace("<td></td>", f'<td><a title="Order Overview" href="OrderOverview.aspx?PublicOrderId={PUBLIC_ID}">Overview</a></td>', 1)
    return f'<table id="{QID}"><thead><tr>{cells(headers,"th")}</tr></thead><tbody><tr>{row_html}</tr></tbody></table><span id="ctl00_ContentPlaceHolder1_lblTaskRecordCount">{count} Record(s) found.</span>{FOOTER}'


def overview_html():
    day = (datetime.now(EASTERN) + timedelta(days=5)).strftime("%m/%d/%Y")
    row = ["", "", "Full Title", "PRODUCT-001", "", "0", "", "9/17/2026 10:11:29 AM", "Tester", "", "", "", "", day + " 01:00 PM [NB]", "5d 0h", "", "", "", "", ""]
    row_html = cells(row).replace("<td></td>", '<td><button title="Add Reminder" id="alarm1" onclick="openForm()">Add Reminder</button></td>', 1)
    headers = ["", "", "Product", "External Product Number", "Originator Product Number", "Skill Grade", "", "Arrival Time", "Created By", "Completed Time", "Delivery Time", "Cancelled Time", "Suspended Time", "SLA/NB", "Status", "", "", "", "", ""]
    return f'''<table id="Table2"><tr><td>Order: TPS-DEMO-001</td></tr></table>
<div id="{RID}"><div id="saved">You have no reminders set.</div>
<div id="{PID}" style="display:none">
<label><input type="radio" name="kind" value="eta" checked>ETA</label>
<table aria-label="RadDatePicker"><tr><td><input id="date" onblur="normalizeEta()"></td>
<td><a href="#" onclick="document.getElementById('clock').style.display='block';return false">Open the time view popup.</a></td></tr></table>
<textarea id="{DID}"></textarea>
<button onclick="save()">Add</button><button onclick="document.getElementById('{PID}').style.display='none'">Cancel</button>
</div></div>
<div id="clock" style="display:none"><a href="#" onclick="chooseTime();return false">5:00 PM</a></div>
<table id="{WID}"><thead><tr>{cells(headers, 'th')}</tr></thead><tbody><tr id="{WID}__0">{row_html}</tr></tbody></table>
{FOOTER}
<script>
function openForm(){{document.getElementById('{PID}').style.display='block';}}
function normalizeEta(){{let e=document.getElementById('date');let a=e.value.match(/^(\\d+)\\/(\\d+)\\/(\\d+)$/);if(a)e.value=Number(a[1])+'/'+Number(a[2])+'/'+a[3]+' 9:00 AM';}}
function chooseTime(){{let e=document.getElementById('date');e.value=e.value.split(' ')[0]+' 5:00 PM';document.getElementById('clock').style.display='none';}}
function save(){{
 let date=document.getElementById('date').value;let msg=document.getElementById('{DID}').value;
 setTimeout(()=>{{let a=date.split(' ')[0].split('/');let due=a[0].padStart(2,'0')+'/'+a[1].padStart(2,'0')+'/'+a[2]+' 05:00 PM';
 let table=document.createElement('table');let tr=table.insertRow();
 [due,'','','(ETA) '+msg,'No','Full Title (09/17/2026 10:11 AM)','TestAccount','today'].forEach(t=>tr.insertCell().textContent=t);
 document.getElementById('saved').replaceChildren(table);document.getElementById('{PID}').style.display='none';}},250);
}}
</script>'''


class BrowserAdapterTests(unittest.TestCase):
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
        self.qhtml = queue_html()
        self.ohtml = overview_html()
        self.context.route("**/*", self.route)
        self.site = TitleVision(headless=True)
        self.site.browser = self.browser
        self.site.context = self.context
        self.site.queue_page = self.context.new_page()
        self.site.detail_page = self.context.new_page()

    def route(self, route):
        body = self.qhtml if "Queues.aspx" in route.request.url else self.ohtml
        route.fulfill(status=200, content_type="text/html", body=body)

    def tearDown(self):
        self.context.close()

    def test_full_form_and_delayed_save(self):
        account, orders = self.site.read_queue()
        self.assertEqual(account, "TestAccount")
        self.assertEqual(len(orders), 1)
        workflows, reminders = self.site.inspect(orders[0], account)
        self.assertEqual(reminders, [])
        workflow = match_workflow(orders[0], workflows)
        plan = Plan(orders[0], workflow, eta_target(workflow.sla), account, datetime.now(EASTERN))
        self.site.prepare(plan)
        self.assertEqual(self.site.reminders(), [])
        self.site.submit()
        self.assertTrue(self.site.wait_saved(plan, timeout=4))
        self.assertEqual(self.site.reminders()[0]["description"], "(ETA) " + COMMENT)
        self.assertTrue(saved_exactly(self.site.reminders(), plan))

    def test_pagination_rejected(self):
        self.qhtml = queue_html(count=100)
        with self.assertRaises(NeedsAttention):
            self.site.read_queue()

    def test_changed_headers_rejected(self):
        self.qhtml = queue_html(headers_changed=True)
        with self.assertRaises(NeedsAttention):
            self.site.read_queue()

    def test_wrong_account_rejected(self):
        account, orders = self.site.read_queue()
        self.ohtml = self.ohtml.replace("logged in as TestAccount", "logged in as OtherAccount")
        with self.assertRaises(NeedsAttention):
            self.site.inspect(orders[0], account)

    def test_wrong_order_rejected(self):
        account, orders = self.site.read_queue()
        self.ohtml = self.ohtml.replace("Order: TPS-DEMO-001", "Order: TPS-DEMO-002")
        with self.assertRaises(NeedsAttention):
            self.site.inspect(orders[0], account)

    def test_nonblank_comments_read(self):
        self.qhtml = queue_html(comment="Preserve this comment")
        account, orders = self.site.read_queue()
        self.assertEqual(orders[0].eta_comment, "Preserve this comment")

    def test_reordered_workflow_columns_rejected(self):
        account, orders = self.site.read_queue()
        self.ohtml = self.ohtml.replace("<th>SLA/NB</th>", "<th>Other Date</th>")
        with self.assertRaises(NeedsAttention):
            self.site.inspect(orders[0], account)

    def test_unreadable_existing_reminders_rejected(self):
        account, orders = self.site.read_queue()
        self.ohtml = self.ohtml.replace("You have no reminders set.", "An existing reminder in an unknown layout")
        with self.assertRaises(NeedsAttention):
            self.site.inspect(orders[0], account)


class PersistentSessionTests(unittest.TestCase):
    def test_open_uses_dedicated_persistent_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile"
            context = FakePersistentContext()
            driver = FakeDriver(context)
            starter = FakePlaywrightStarter(driver)
            with patch("playwright.sync_api.sync_playwright", return_value=starter):
                site = TitleVision(headless=True, profile_dir=profile)
                site.open()

            self.assertTrue(profile.is_dir())
            self.assertEqual(driver.chromium.calls[0][0], str(profile))
            options = driver.chromium.calls[0][1]
            self.assertEqual(options["channel"], "msedge")
            self.assertTrue(options["headless"])
            self.assertEqual(options["viewport"], {"width": 1360, "height": 900})
            self.assertEqual(len(context.pages), 2)
            self.assertEqual(context.pages[0].url, QUEUE_URL)
            self.assertTrue(context.pages[0].front)
            self.assertEqual(context.default_timeout, 15000)
            self.assertEqual(context.navigation_timeout, 45000)

            site.close()
            self.assertTrue(context.closed)
            self.assertTrue(driver.stopped)

    def test_profile_directory_is_stable_across_instances(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "saved-profile"
            self.assertEqual(TitleVision(profile_dir=profile).profile_dir, profile)
            self.assertEqual(TitleVision(profile_dir=profile).profile_dir, profile)


if __name__ == "__main__":
    unittest.main()

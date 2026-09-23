"""Visible browser adapter for the TitleVision interface observed September 2026.

All changes go through the site's ETA form. No private APIs or stored passwords.
"""
from datetime import datetime
import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse, urljoin

from rules import (COMMENT, EASTERN, QUEUE_URL, NeedsAttention, Order,
                   Workflow, clean, order_url, parse_time)

QUEUE = "#ctl00_ContentPlaceHolder1_rdgTaskSummary_ctl00"
WORKFLOWS = "#ctl00_ContentPlaceHolder1_grdWorkflowInstances_ctl00"
REMINDERS = "#ctl00_ContentPlaceHolder1_ucReminders_pnlReminder"
POPUP = "#ctl00_ContentPlaceHolder1_ucReminders_PopupAddEditReminder"
DESCRIPTION = "#ctl00_ContentPlaceHolder1_ucReminders_txtDescription"

QUEUE_READ = """table => {
 const headers = [...table.querySelectorAll('thead th')].map(e => e.innerText.trim());
 const rows = [...table.querySelectorAll('tr')].filter(r =>
   [...r.children].some(c => c.querySelector('a[title="Order Overview"]')));
 return {headers, text:table.innerText, rows: rows.map(r => ({
   cells: [...r.children].filter(e => e.tagName==='TD').map(e => e.innerText.trim()),
   href: r.querySelector('a[title="Order Overview"]').getAttribute('href')
 }))};
}"""

WORKFLOW_READ = """table => [...table.querySelectorAll('tr')].filter(r =>
 /^ctl00_ContentPlaceHolder1_grdWorkflowInstances_ctl00__\\d+$/.test(r.id)
 ).map(r => ({cells: [...r.children].filter(e => e.tagName==='TD').map(e => e.innerText.trim()),
 alarm: r.querySelector('[title="Add Reminder"]')?.id || ''}))"""

REMINDER_READ = r"""panel => [...panel.querySelectorAll('tr')].filter(r =>
 !r.closest('[id$="PopupAddEditReminder"]') &&
 ![...r.children].some(c => c.querySelector('table'))
 ).map(r => {
 const c = [...r.children].filter(e => e.tagName==='TD').map(e => e.innerText.replace(/\s+/g,' ').trim());
 const edit = [...r.querySelectorAll('a,button,input')].filter(e =>
   (e.innerText || e.value || '').trim() === 'Edit');
 return {c, edit:edit.length === 1 ? edit[0] : null};
 }).filter(x => x.c.length > 1 || /^\(ETA\)/.test(x.c[0] || ''))
 .map(({c,edit}) => ({due:c[0],description:c[3],related:c[5],columns:c.length,
 edit_id:edit?.id || '',edit_href:edit?.getAttribute('href') || ''}))"""


class TitleVision:
    def __init__(self, headless=False, profile_dir=None):
        self.headless = headless
        default_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".titlevision-assistant"))
        self.profile_dir = Path(profile_dir or os.environ.get(
            "TITLEVISION_PROFILE_DIR", default_root / "TitleVisionAssistant" / "browser-profile"))
        self.driver = self.browser = self.context = None
        self.queue_page = self.detail_page = None
        self.sla_queue_url = None
        self.check_stop = lambda: None

    def open(self):
        from playwright.sync_api import sync_playwright
        self.close()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.driver = sync_playwright().start()
        errors = []
        for channel in ("msedge", "chrome"):
            try:
                self.context = self.driver.chromium.launch_persistent_context(
                    str(self.profile_dir), channel=channel, headless=self.headless,
                    viewport={"width": 1360, "height": 900})
                self.browser = self.context.browser
                break
            except Exception:
                errors.append(channel)
        if self.context is None:
            self.close()
            raise NeedsAttention(
                "Could not open the saved Edge or Chrome session. Close any other TitleVision "
                "Assistant browser window, then try again. Also check that Edge or Chrome is installed "
                "and allowed by your company.")
        self.context.set_default_timeout(15000)
        self.context.set_default_navigation_timeout(45000)
        self.queue_page = self.context.new_page()
        self.detail_page = self.context.new_page()
        self.queue_page.bring_to_front()
        try:
            self.queue_page.goto(QUEUE_URL, wait_until="domcontentloaded")
        except Exception:
            if not self.queue_page.url.startswith("https://"):
                raise NeedsAttention("The sign-in page could not be opened. Check the connection.")

    def require_open(self):
        if not self.context or not self.queue_page or self.queue_page.is_closed():
            raise NeedsAttention("Open the browser and sign in to TitleVision first.")

    def account(self, page):
        if urlparse(page.url).hostname != "tv.datatracetitle.com":
            raise NeedsAttention("Sign in to TitleVision in the app's browser, then preview again.")
        text = page.locator("body").inner_text()
        match = re.search(r"You are currently logged in as\s+([^\r\n]+?)\.(?:\s|$)", text)
        if not match:
            raise NeedsAttention("The signed-in TitleVision account could not be verified.")
        return clean(match[1])

    def _navigate(self, page, url):
        try:
            page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            raise NeedsAttention("The page could not be refreshed. Check your connection and sign-in, then preview again.") from exc

    def read_queue(self):
        self.require_open()
        self._navigate(self.queue_page, QUEUE_URL)
        if urlparse(self.queue_page.url).hostname != "tv.datatracetitle.com":
            raise NeedsAttention("Finish signing in, then click Preview orders.")
        self.queue_page.locator(QUEUE).wait_for(state="visible", timeout=30000)
        account = self.account(self.queue_page)
        data = self.queue_page.locator(QUEUE).evaluate(QUEUE_READ)
        expected_columns = {1: "Order Number", 5: "Online/ Ground", 7: "Product", 18: "ETA Comments", 21: "Arrival Time"}
        if any(i >= len(data["headers"]) or clean(data["headers"][i]) != label
               for i, label in expected_columns.items()):
            raise NeedsAttention("The queue column layout has changed. No orders were updated.")
        # The observed queue has a leading overview column followed by 24 data columns.
        orders = []
        for row in data["rows"]:
            c = row["cells"]
            if len(c) != 25 or not c[1].startswith("TPS-"):
                raise NeedsAttention("The queue row layout has changed. No orders were updated.")
            if c[5] == "Ground":
                orders.append(Order(c[1], c[7], c[21], order_url(row["href"]), c[18], c[5]))
        count_text = self.queue_page.locator("#ctl00_ContentPlaceHolder1_lblTaskRecordCount").inner_text()
        match = re.search(r"([\d,]+)\s+Record", count_text)
        if not match or int(match[1].replace(",", "")) != len(data["rows"]):
            raise NeedsAttention("The queue is paginated or its count changed. Show all rows and preview again; nothing was updated.")
        return account, orders

    def read_sla_queue(self):
        """Discover the named queue through the site's navigation, never guess a qid."""
        self.require_open()
        self.check_stop()
        page = self.queue_page
        if not self.sla_queue_url:
            self.account(page)
            links = page.get_by_role("link", name=re.compile(r"^All\s+Active\s*(?:&|and|\/)\s*Available(?:\s+Tasks)?\s*\*?$", re.I))
            if links.count() != 1:
                raise NeedsAttention("Open the TitleVision navigation showing 'All Active & Available', then preview again. The Ground queue will not be used for SLA recovery.")
            destination = urljoin(page.url, links.get_attribute("href") or "")
            parsed = urlparse(destination)
            if parsed.scheme != "https" or parsed.netloc != "tv.datatracetitle.com" or parsed.path.lower() != "/queues.aspx" or not parsed.query:
                raise NeedsAttention("The All Active & Available queue link could not be verified.")
            self.sla_queue_url = destination
        self._navigate(page, self.sla_queue_url)
        page.locator(QUEUE).wait_for(state="visible", timeout=30000)
        account = self.account(page)
        count_text = page.locator("#ctl00_ContentPlaceHolder1_lblTaskRecordCount").inner_text()
        match = re.search(r"([\d,]+)\s+Record", count_text)
        if not match:
            raise NeedsAttention("The total task count could not be read.")
        total = int(match[1].replace(",", ""))
        orders, seen_pages, read_count = [], set(), 0
        while True:
            self.check_stop()
            data = page.locator(QUEUE).evaluate(QUEUE_READ)
            live_count = page.locator("#ctl00_ContentPlaceHolder1_lblTaskRecordCount").inner_text()
            if clean(live_count) != clean(count_text):
                raise NeedsAttention("The task count changed during the scan. Preview again.")
            headers = [clean(h).rstrip("*").strip() for h in data["headers"]]
            required = ("Order Number", "Product", "Arrival Time", "ETA Comments", "Online/ Ground",
                        "St", "County", "Client", "Task Status", "SLA Expiration")
            if any(headers.count(name) != 1 for name in required):
                raise NeedsAttention("The Active/Available queue columns changed. No orders were updated.")
            index = {name: headers.index(name) for name in required}
            fingerprint = repr(data["rows"])
            if fingerprint in seen_pages:
                raise NeedsAttention("Queue pagination repeated a page. Show all tasks and preview again.")
            seen_pages.add(fingerprint)
            for row in data["rows"]:
                c = row["cells"]
                if len(c) != len(headers):
                    raise NeedsAttention("An Active/Available task row has an unexpected layout.")
                value = lambda name: c[index[name]]
                if not value("Order Number").startswith("TPS-"):
                    raise NeedsAttention("An order number could not be verified.")
                read_count += 1
                if clean(value("Task Status")).casefold() in {"active", "available", "in progress"}:
                    orders.append(Order(value("Order Number"), value("Product"), value("Arrival Time"),
                                        order_url(row["href"]), value("ETA Comments"), value("Online/ Ground"),
                                        value("St"), value("County"), value("Client"), value("Task Status"),
                                        value("SLA Expiration")))
            if read_count == total:
                break
            if read_count > total or not data["rows"]:
                raise NeedsAttention("The task count changed during preview. Preview again.")
            next_page = page.get_by_role("button", name=re.compile(r"^Next Page$", re.I)).or_(
                page.get_by_role("link", name=re.compile(r"^Next Page$", re.I)))
            if next_page.count() != 1 or not next_page.is_enabled():
                raise NeedsAttention("Not all Active/Available tasks are visible. Choose Show all rows in TitleVision, then preview again.")
            next_page.click()
            page.wait_for_function("([selector, previous]) => { const t=document.querySelector(selector); return t && t.innerText !== previous; }",
                                   arg=[QUEUE, data["text"]])
            if self.account(page) != account:
                raise NeedsAttention("The account changed while reading tasks.")
        return account, orders

    def inspect(self, order, account):
        self._navigate(self.detail_page, order.url)
        if self.account(self.detail_page) != account:
            raise NeedsAttention("The signed-in account changed. Open a new preview.")
        header = self.detail_page.locator("#Table2").inner_text()
        if not re.search(r"(?<![\w-])" + re.escape(order.number) + r"(?![\w-])", header):
            raise NeedsAttention("The order overview does not match the selected order.")
        self.detail_page.locator(WORKFLOWS).wait_for(state="visible")
        headers = self.detail_page.locator(WORKFLOWS).locator("thead th").all_inner_texts()
        expected_columns = {2: "Product", 3: "External Product Number", 7: "Arrival Time",
                            9: "Completed Time", 10: "Delivery Time", 11: "Cancelled Time", 13: "SLA/NB"}
        if any(i >= len(headers) or clean(headers[i]) != label for i, label in expected_columns.items()):
            raise NeedsAttention("The product table columns changed. This order needs review.")
        records = self.detail_page.locator(WORKFLOWS).evaluate(WORKFLOW_READ)
        workflows = []
        for row in records:
            c = row["cells"]
            if len(c) != 20:
                raise NeedsAttention("The product table layout changed. This order needs review.")
            workflows.append(Workflow(c[2], c[3], c[7], c[13], row["alarm"], c[9], c[10], c[11], c[12]))
        if not workflows:
            raise NeedsAttention("No product rows could be read on this order.")
        return workflows, self.reminders()

    def reminders(self):
        panel = self.detail_page.locator(REMINDERS)
        records = panel.evaluate(REMINDER_READ)
        for record in records:
            if record.pop("columns", 0) < 8 or not record.get("description") or not record.get("related"):
                raise NeedsAttention("An existing reminder could not be read safely. Check this order manually.")
            try:
                parse_time(record.get("due"))
            except NeedsAttention as exc:
                raise NeedsAttention("An existing reminder date could not be read safely. Check this order manually.") from exc
        if not records and "You have no reminders set." not in panel.inner_text():
            raise NeedsAttention("The existing reminder list could not be read safely. Check this order manually.")
        return records

    def prepare(self, plan):
        from playwright.sync_api import expect
        page = self.detail_page
        old = getattr(plan, "old_reminder", ())
        if old:
            from sla import reminder_snapshot
            if sum(reminder_snapshot(r) == old for r in self.reminders()) != 1:
                raise NeedsAttention("The ETA changed before Edit. Preview again.")
            def exact_text(value):
                return re.compile(r"^\s*" + r"\s+".join(re.escape(v).replace("/", r"\/") for v in value.split()) + r"\s*$")
            row = page.locator(REMINDERS).locator("tr").filter(
                has=page.get_by_role("cell", name=exact_text(old[0]))).filter(
                has=page.get_by_role("cell", name=exact_text(old[1]))).filter(
                has=page.get_by_role("cell", name=exact_text(old[2])))
            edit = row.get_by_role("link", name="Edit", exact=True).or_(row.get_by_role("button", name="Edit", exact=True))
            if row.count() != 1 or edit.count() != 1:
                raise NeedsAttention("Could not uniquely locate the matching ETA Edit link.")
            edit.click()
        else:
            alarm = page.locator('[id="' + plan.workflow.alarm_id + '"]')
            if not plan.workflow.alarm_id or alarm.count() != 1:
                raise NeedsAttention("The active product's alarm button is unavailable.")
            alarm.click()
        popup = page.locator(POPUP)
        popup.wait_for(state="visible")
        popup.get_by_role("radio", name="ETA", exact=True).check()
        date_input = popup.get_by_role("table", name="RadDatePicker", exact=True).get_by_role("textbox")
        if old:
            previous_description = re.sub(r"^\(ETA\)\s*", "", old[1])
            if (parse_time(date_input.input_value()) != parse_time(old[0]) or
                    clean(page.locator(DESCRIPTION).input_value()) != clean(previous_description)):
                self.cancel_form()
                raise NeedsAttention("The Edit form does not match the original ETA date and comment. Preview again.")
        date_input.fill(plan.date)
        page.locator(DESCRIPTION).fill(plan.comment)
        popup.get_by_role("link", name="Open the time view popup.", exact=True).click()
        page.get_by_role("link", name="5:00 PM", exact=True).click()
        expected = re.compile(rf"^0?{plan.target.month}/0?{plan.target.day}/{plan.target.year} 0?5:00 PM$")
        expect(date_input).to_have_value(expected)
        expect(page.locator(DESCRIPTION)).to_have_value(plan.comment)
        if not popup.get_by_role("radio", name="ETA", exact=True).is_checked():
            raise NeedsAttention("The form is not set to ETA.")

    def submit(self):
        # Never automatically retry this click, even if it times out.
        button = self.detail_page.locator(POPUP).get_by_role("button", name=re.compile(r"^(?:Add(?: Reminder)?|Update(?: Reminder)?|Save(?: Changes)?)$", re.I))
        if button.count() != 1:
            raise NeedsAttention("The ETA save action could not be uniquely identified.")
        button.click()

    def wait_saved(self, plan, timeout=35):
        from rules import saved_exactly
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if saved_exactly(self.reminders(), plan):
                return True
            self.detail_page.wait_for_timeout(350)
        return False

    def cancel_form(self):
        if self.detail_page and not self.detail_page.is_closed():
            popup = self.detail_page.locator(POPUP)
            if popup.is_visible():
                popup.get_by_role("button", name="Cancel", exact=True).click()

    def close(self):
        if self.context:
            try:
                self.context.close()
            except Exception:
                pass
        if self.driver:
            try:
                self.driver.stop()
            except Exception:
                pass
        self.driver = self.browser = self.context = None
        self.queue_page = self.detail_page = None

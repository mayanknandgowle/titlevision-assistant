"""TitleVision Ground ETA rules. No network or UI dependencies."""
from dataclasses import dataclass
from datetime import datetime, time
import hashlib
import re
from urllib.parse import urljoin, urlparse, parse_qs
from zoneinfo import ZoneInfo

BASE_URL = "https://tv.datatracetitle.com/"
QUEUE_URL = BASE_URL + "Queues.aspx?qid=24003"
COMMENT = "Hello, Order has been assigned to the abstractor, and we will ensure completion within SLA"
EASTERN = ZoneInfo("America/New_York")


class NeedsAttention(Exception):
    pass


class Stopped(Exception):
    pass


def clean(value):
    return " ".join(str(value or "").split())


def parse_time(value):
    value = clean(value)
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise NeedsAttention("An arrival time could not be read. This order needs manual review.")


def order_url(href):
    url = urljoin(BASE_URL, href)
    parts = urlparse(url)
    public_id = parse_qs(parts.query).get("PublicOrderId", [""])[0]
    if (parts.scheme != "https" or parts.netloc != "tv.datatracetitle.com"
            or parts.path.lower() != "/orderoverview.aspx"
            or not re.fullmatch(r"[0-9a-fA-F-]{36}", public_id)):
        raise NeedsAttention("An order link has an unexpected destination.")
    return url


@dataclass(frozen=True)
class Order:
    number: str
    product: str
    arrival: str
    url: str
    eta_comment: str = ""
    mode: str = "Ground"
    state: str = ""
    county: str = ""
    client: str = ""
    task_status: str = ""
    sla_expiration: str = ""

    @property
    def key(self):
        raw = self.url + "|" + str(parse_time(self.arrival).replace(second=0)) + "|" + self.product
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class Workflow:
    product: str
    external_id: str
    arrival: str
    sla: str
    alarm_id: str
    completed: str = ""
    delivered: str = ""
    cancelled: str = ""
    suspended: str = ""

    @property
    def active(self):
        return not (self.completed or self.delivered or self.cancelled or self.suspended)


@dataclass(frozen=True)
class Plan:
    order: Order
    workflow: Workflow
    target: datetime
    account: str
    scanned_at: datetime

    @property
    def comment(self):
        return COMMENT

    @property
    def operation_key(self):
        return self.order.key

    @property
    def date(self):
        return self.target.strftime("%m/%d/%Y")

    @property
    def related(self):
        return f"{self.workflow.product} ({parse_time(self.workflow.arrival):%m/%d/%Y %I:%M %p})"


def match_workflow(order, workflows):
    minute = parse_time(order.arrival).replace(second=0)
    name = clean(order.product)
    truncated = name.endswith(("..", "\u2026"))
    prefix = name.rstrip(".\u2026 ").casefold()
    if not prefix:
        raise NeedsAttention("The queue product name is missing.")
    matches = [w for w in workflows if w.active
               and parse_time(w.arrival).replace(second=0) == minute
               and (clean(w.product).casefold().startswith(prefix) if truncated
                    else clean(w.product).casefold() == prefix)]
    if len(matches) != 1:
        raise NeedsAttention("Could not uniquely match the active product and arrival time.")
    return matches[0]


def eta_target(sla, now=None):
    match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{4})\b", sla)
    if not match:
        raise NeedsAttention("The active product has no readable SLA/NB date.")
    try:
        day = datetime.strptime(match[1], "%m/%d/%Y").date()
    except ValueError as exc:
        raise NeedsAttention("The SLA/NB date is invalid.") from exc
    target = datetime.combine(day, time(17), tzinfo=EASTERN)
    if target <= (now or datetime.now(EASTERN)):
        raise NeedsAttention("SLA/NB at 5 PM Eastern is already past. Review this order manually.")
    return target


def plan_is_current(plan, now=None):
    now = now or datetime.now(EASTERN)
    return 0 <= (now - plan.scanned_at).total_seconds() <= 1800 and plan.target > now


def matching_reminders(rows, related):
    return [r for r in rows if clean(r.get("related")) == clean(related)
            and clean(r.get("description")).startswith("(ETA)")]


def saved_exactly(rows, plan):
    expected = plan.target.replace(tzinfo=None)
    matched = matching_reminders(rows, plan.related)
    saved = []
    for row in matched:
        try:
            if parse_time(row.get("due")) == expected and clean(row.get("description")) == "(ETA) " + plan.comment:
                saved.append(row)
        except NeedsAttention:
            continue
    if getattr(plan, "old_reminder", ()):
        # Editing must replace exactly one ETA; an accidental additional reminder fails verification.
        return len(matched) == 1 and len(saved) == 1
    return bool(saved)

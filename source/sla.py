"""Expired SLA planning. No browser calls or generated factual explanations.

Reasons are derived from ETA notes.docx. State/client suggestions come from
SLA comments.xlsx, Sheet1 A2:C8. Geography suggests wording, never proves a delay.
"""
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
import hashlib
import json
import re

from rules import EASTERN, NeedsAttention, Plan, clean, matching_reminders, parse_time

POLICY_VERSION = "sla-v1-weekdays"
# Deliberately omit unverified claims such as 'we requested a rush'.
REASONS = {
    "Court case copies pending": "the required court case copies remain pending",
    "Judgment copies pending": "the required judgment copies remain pending",
    "County clerk documents pending": "the required documents remain pending with the county clerk",
    "Tax information pending": "the required tax information remains pending",
    "Prothonotary results pending": "the prothonotary search results remain pending",
    "Attorney opinion pending": "the attorney opinion certificate remains pending",
    "Revised search package pending": "the corrected search package remains pending",
    "Recorder website unavailable": "the county recorder website remains unavailable",
    "Complex or historical search": "additional historical record review is required to complete the search",
    "Limited county/searcher availability": "limited county access or searcher availability has delayed completion",
    "Prior deed copies pending": "the prior deed copies required for the chain of title remain pending",
    "Foreclosure documents pending": "the required foreclosure documents remain pending",
    "Probate or surrogate records pending": "the required probate or surrogate records remain pending",
    "Complete mortgage copy pending": "the complete recorded mortgage copy remains pending",
    "Legal description discrepancy": "the legal description discrepancy requires further review",
    "Ownership or borrower mismatch": "clarification of the ownership or borrower information remains pending",
    "Assignment or satisfaction review": "the assignment or satisfaction documents require further review",
    "Multiple parcel searches": "the searches and document reviews for all parcels require additional time",
    "Name and judgment review": "the volume of name, judgment, and lien entries requires additional review",
    "Recorded document not indexed": "the recently recorded document is not yet available in the county index",
}

# Approved source wording; the operator confirms the entire preview, including
# factual claims about completed searches and requested documents.
STATE_TEMPLATES = {
    "Judgment copies pending": "ON HOLD: Hello, We have completed the search and requested the judgment copies with the county clerk and are awaiting it. We will have this order delivered as soon as we receive the copies from them. The ETA will be {date} EOB.",
    "Attorney opinion pending": "Hello, We have completed the search and requested the attorney opinion from the abstractor. We will have this delivered once we receive the attorney opinion certificate. The ETA will be {date} EOB.",
    "Prothonotary results pending": "Hello, We have requested and waiting for the prothonotary search results, and we will have this delivered as soon as we receive the protho results. The ETA will be {date} EOB.",
}


def policy_reason(order):
    state, client = clean(order.state).upper(), clean(order.client).upper()
    if state == "MD" and client == "TELSIX":
        return "Judgment copies pending"
    if state in {"SC", "LA", "NC", "WV", "GA"} and client == "VYLLAMMP":
        return "Attorney opinion pending"
    if state == "PA":
        return "Prothonotary results pending"
    return ""


def reason_suggestion(order, existing_text):
    """Suggestions only: a previous comment does not establish today's facts."""
    patterns = {
        "Court case copies pending": r"court case cop",
        "Judgment copies pending": r"judgment cop",
        "County clerk documents pending": r"documents? (?:from|with) the county clerk",
        "Tax information pending": r"tax information|treasurer",
        "Prothonotary results pending": r"prothonotary|protho results",
        "Attorney opinion pending": r"attorney opinion",
        "Revised search package pending": r"revised search package|corrected package|chain of title did not match",
        "Recorder website unavailable": r"(?:recorder|county).*website",
        "Complex or historical search": r"historical|60.year|depth and complexity|prior to the owner policy",
        "Limited county/searcher availability": r"rural county|limited (?:county|searcher)",
        "Prior deed copies pending": r"prior deed cop",
        "Foreclosure documents pending": r"foreclosure",
        "Probate or surrogate records pending": r"probate|surrogate|estate records",
        "Complete mortgage copy pending": r"incomplete mortgage|complete (?:recorded )?mortgage|full mortgage copy",
        "Legal description discrepancy": r"legal description",
        "Ownership or borrower mismatch": r"ownership discrepancy|ownership.*clarification|mismatch.*owner",
        "Assignment or satisfaction review": r"assignment|satisfaction",
        "Multiple parcel searches": r"multiple parcels|all parcels|each parcel",
        "Name and judgment review": r"name and judgment|volume of records|name, judgment",
        "Recorded document not indexed": r"not yet.*index|being indexed|not indexed|indexing system",
    }
    matches = [reason for reason, pattern in patterns.items() if re.search(pattern, existing_text, re.I)]
    if len(matches) == 1:
        return matches[0], "Prior ETA wording suggests this reason; verify its current accuracy"
    if len(matches) > 1:
        return "", "Prior ETA mentions multiple reasons; select the current delay"
    reason = policy_reason(order)
    return reason, "State/client suggestion from SLA comments.xlsx" if reason else "Select a reason from ETA notes.docx"


def sla_time(value):
    match = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s+[AP]M\b", clean(value), re.I)
    if not match:
        raise NeedsAttention("The product SLA/NB timestamp is unreadable; no date was inferred.")
    return parse_time(match[0].upper()).replace(tzinfo=EASTERN)


def five_workdays(base, holidays=()):
    """Exclude the base date. Default calendar is Monday-Friday, not assumed holidays."""
    day = base.astimezone(EASTERN).date()
    remaining = 5
    while remaining:
        day += timedelta(days=1)
        if day.weekday() < 5 and day not in holidays:
            remaining -= 1
    return datetime.combine(day, time(17), tzinfo=EASTERN)


def reminder_snapshot(row):
    return tuple(clean(row.get(k)) for k in ("due", "description", "related", "edit_id", "edit_href"))


@dataclass(frozen=True)
class SLAPlan(Plan):
    old_reminder: tuple = ()
    base_eta: str = ""
    reason: str = ""
    reason_source: str = ""
    approved: bool = False
    policy: str = POLICY_VERSION

    @property
    def comment(self):
        if self.reason not in REASONS:
            raise NeedsAttention("Select and confirm a delay reason before updating this order.")
        if self.reason == policy_reason(self.order):
            return STATE_TEMPLATES[self.reason].format(date=self.target.strftime("%m/%d"))
        prefix = "ON HOLD: " if (self.order.state.upper() == "MD" and
                                     self.order.client.upper() == "TELSIX" and
                                     self.reason == "Judgment copies pending") else ""
        return (prefix + "Hello, the order could not be delivered within the previous ETA because "
                + REASONS[self.reason] + ". The revised ETA is "
                + self.target.strftime("%m/%d/%Y") + " at 5:00 PM Eastern.")

    @property
    def operation_key(self):
        # Same source revision remains one operation even if the selected reason changes.
        raw = json.dumps([self.account, self.order.key, self.workflow.external_id,
                          self.old_reminder, self.base_eta, self.target.isoformat(), self.policy])
        return "sla:" + hashlib.sha256(raw.encode()).hexdigest()


def make_sla_plan(order, workflow, reminders, account, now=None):
    now = now or datetime.now(EASTERN)
    if clean(order.task_status).casefold() not in {"active", "available", "in progress"}:
        raise NeedsAttention("Task is not Active or Available.")
    if not workflow.active:
        raise NeedsAttention("Product is completed, delivered, cancelled, or suspended.")
    if sla_time(workflow.sla) >= now:
        raise NeedsAttention("The product SLA has not expired.")
    related = Plan(order, workflow, now, account, now).related
    existing = matching_reminders(reminders, related)
    if len(existing) > 1:
        raise NeedsAttention("Multiple ETAs match this product. Select the correct reminder in TitleVision manually.")
    old = existing[0] if existing else None
    if not old and clean(order.eta_comment):
        raise NeedsAttention("The queue shows an ETA comment but no matching product ETA could be found. Review the order manually.")
    base = parse_time(clean(old["due"])).replace(tzinfo=EASTERN) if old else sla_time(workflow.sla)
    if old and base >= now:
        raise NeedsAttention("This product already has a future ETA; no additional extension is needed.")
    if old and not (old.get("edit_id") or old.get("edit_href")):
        raise NeedsAttention("The matching ETA has no unique Edit action.")
    if not old and not workflow.alarm_id:
        raise NeedsAttention("This product has no Add Reminder action.")
    target = five_workdays(base)
    if target <= now:
        raise NeedsAttention("ETA + five weekdays is still in the past. Review the deadline manually.")
    reason, source = reason_suggestion(order, old["description"] if old else order.eta_comment)
    return SLAPlan(order, workflow, target, account, now,
                   reminder_snapshot(old) if old else (), base.isoformat(), reason,
                   source)


def approve_reason(plan, reason):
    if reason not in REASONS:
        raise NeedsAttention("Select a supported delay reason.")
    return replace(plan, reason=reason, reason_source="Operator confirmed", approved=True)


def same_sla_task(before, after):
    # Queue SLA expiration is a ticking elapsed duration, not the contractual date.
    # The full product SLA timestamp is separately revalidated below.
    return replace(before, sla_expiration="") == replace(after, sla_expiration="")


def unchanged_sla_plan(preview, current):
    return (same_sla_task(preview.order, current.order) and preview.workflow.external_id == current.workflow.external_id
            and preview.workflow.sla == current.workflow.sla
            and preview.workflow.product == current.workflow.product
            and preview.old_reminder == current.old_reminder and preview.target == current.target
            and preview.account == current.account)

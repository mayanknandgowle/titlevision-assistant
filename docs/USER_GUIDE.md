# User guide

Open the browser, sign in directly to TitleVision, choose the workflow and preview. Review the proposed ETA and comment. SLA rows require a confirmed delay reason before becoming Ready. Run updates applies all Ready rows.

Ground mode preserves existing comments and uses the product SLA calendar date at 5 PM Eastern. SLA mode edits a matching expired ETA to five weekdays after its previous date, at 5 PM Eastern. It can add a missing ETA when the queue comment is blank, using expired SLA as the starting point. Holidays are not excluded.

Use the outer scrollbar to reach the full comment preview and history controls on smaller displays. Try demo is read-only synthetic Ground data.

Use **Import previous history** before operational work when moving from an older app folder. Select `data/history.sqlite3` from that folder. Export history produces CSV for review. History and browser sessions are retained when upgrading or uninstalling.

The ↻ update button checks GitHub Releases. The app checks once on startup without interrupting with a dialog. Downloading requires confirmation; installer launch is permitted only for matching trusted publisher signatures. Unsigned builds require manual installation.

## Needs review

A changed product, ambiguous reminder, unreadable date, failed refresh or unconfirmed save blocks further action. Do not repeatedly click or delete history to retry an uncertain save. Check TitleVision directly and keep the audit record. The current app has no automatic reconciliation tool.

If signing in again is required, use TitleVision's own login page. The app never collects passwords. A persistent profile cannot override DataTrace session expiry or MFA policy.

This version still requires a supervised live SLA acceptance test before broad production batches.

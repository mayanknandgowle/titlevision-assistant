# Validation — September 23, 2026

## Local automated result

**97 tests passed** on Windows with Python 3.13 and installed Microsoft Edge.

Coverage includes Ground and SLA rules, Eastern time/DST, five-weekday arithmetic, state/client templates, reason confirmation, strict product matching, suspended/completed products, future ETAs, ambiguous reminders, stale previews, source changes, stop handling, atomic reservations, uncertain-save blocking, and CSV export.

Browser tests intercept all network requests with synthetic pages. They exercise queue discovery, pagination, matching Edit actions, mismatched forms, date/time/comment entry and single-reminder verification. New regressions reject partly unreadable reminder lists and failed same-URL navigation.

Updater tests cover numeric version comparison, drafts/prereleases, downgrades, missing/duplicate assets, host and URL restrictions, response/size bounds, missing digests, corrupted/truncated/oversize downloads, cancellation, path traversal, changed files and publisher-signature decisions. No installer is executed by these tests.

History tests verify migration without overwriting existing data, idempotent import and rollback on conflicting audit records.

## Desktop and packaging

The previous packaged build was opened, its demo submission remained disabled and its outer scrollbar reached review/history controls at current Windows scaling. The current release adds the update button, version metadata and stable-history import. Independent CI and current-package smoke checks are recorded in GitHub Actions and release review; do not infer production acceptance from a successful build.

## Live compatibility observations

Earlier read-only checks inspected the Ground queue, product table and ETA form. The real All Active and Available Tasks* label and In Progress status informed the adapter. No live SLA reminder was saved during development.

An isolated Edge restart probe retained a persistent cookie but not a session-only cookie. This does not establish DataTrace's actual login behavior. The app no longer promises indefinite session retention.

## Required supervised acceptance

- Preview real SLA tasks with an authorized account.
- Confirm one actual delay reason and deadline, supervise one save, and verify the existing reminder was edited correctly.
- Close/reopen to validate actual DataTrace authentication behavior.
- Test installation and upgrade on a clean Windows machine, including imported history.
- Configure trusted publisher signing before claiming automatic installation support.

Holidays are not excluded. Additional county rules are not inferred from state/client templates. Site layout changes may require adapter updates. No security or regulatory certification is claimed.

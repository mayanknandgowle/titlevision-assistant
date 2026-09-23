# Changelog

## 0.2.0 — 2026-09-23

### Added
- In-app GitHub release checks, download progress and cancellation.
- Bounded HTTPS downloads, SHA-256 verification and matching-publisher checks before installer launch.
- Stable user history storage and conflict-safe legacy history import.
- Versioned Windows bundle, per-user installer definition and draft-release workflow.
- Hash-locked Windows build dependencies, CI checks and contributor/security documentation.

### Fixed
- Partly unreadable reminder lists now block updates instead of silently omitting rows.
- Failed same-URL navigation now blocks stale-data revalidation.
- Sign-in text no longer promises that session-only authentication always survives restart.

### Existing workflows
- Ground blank-ETA updates and reviewed expired-SLA reminder edits.
- Five-weekday deadline calculation at 5 PM Eastern.
- Local journal, duplicate reservations, uncertain-save blocking and CSV export.

### Validation boundaries
- The initial artifacts are unsigned unless publisher signing is configured.
- Live SLA save and authentication-restart acceptance remain outstanding.
- Weekdays exclude weekends only; an approved holiday calendar is not configured.

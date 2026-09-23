# Architecture

## Design choice

A modular, single-process Windows desktop application suits a small operator-driven automation tool. There is no server, cloud database or AI API. Python/Tkinter provides the interface, Playwright drives a dedicated visible browser and SQLite records local attempts.

## Boundaries

| Module | Responsibility |
| --- | --- |
| `app.py` | Tk widgets, command queue, event handling and user review |
| `rules.py` / `sla.py` | Product matching, Eastern time, deadlines, reasons and immutable plans |
| `engine.py` / `sla_engine.py` | Preview, revalidate, reserve, submit once, verify |
| `titlevision.py` | Page navigation, DOM parsing, form input and saved-row reading |
| `journal.py` | Atomic reservations, results, audit export and conflict-safe history import |
| `paths.py` | Stable data location and non-overwriting legacy migration |
| `updates.py` | GitHub release selection, bounded download, digest and publisher checks |
| `appmeta.py` | Application version and configured update repository |

The UI thread owns Tk. One worker thread owns Playwright and its SQLite connection. Commands serialize browsing and updates so installation cannot begin in the middle of an order submission. Network update checks run off the UI thread. Startup checks notify through the status/button; downloads and installation require user action.

## Write lifecycle

`Preview → confirm reason → re-read source → prepare form → reserve intent → one submission → verify → record`

No claim of exactly-once server semantics is made: browser timeouts can leave outcomes uncertain. The journal blocks automatic retry and asks the operator to inspect TitleVision. A remote site's concurrent changes cannot be made transactional by this client.

## Persistence

History: `%LOCALAPPDATA%\TitleVisionAssistant\data\history.sqlite3`.
Browser profile: `%LOCALAPPDATA%\TitleVisionAssistant\browser-profile`.
Downloaded installers: `%LOCALAPPDATA%\TitleVisionAssistant\updates`.

A legacy adjacent history is copied only when the stable database does not exist. The import action merges records atomically and refuses conflicts. Neither upgrades nor uninstall delete history or browser sessions. Users should use one working installation and retain backups before an upgrade.

## Update trust

The fixed public repository exposes stable GitHub Releases. Versions are strict numeric `major.minor.patch`; prereleases and drafts are excluded. The expected installer name, repository URL, bounded size and GitHub SHA-256 must match. Redirects are restricted to GitHub download hosts. Before automatic launch the app hashes the file again and requires both itself and the installer to have valid Authenticode signatures with the same certificate thumbprint.

Unsigned builds only support verified download plus manual installation. Certificate rotation currently requires a manual trust transition. A compromised publisher/repository remains a supply-chain risk; protect the GitHub account, review releases and protect signing keys. Checksums alone are not publisher authentication.

## Deferred work

Live compatibility acceptance, an approved holiday calendar, diagnostic log retention, an explicit uncertain-operation reconciliation UI, single-instance enforcement, broader accessibility testing and approved additional geography policies remain separate work. This project does not claim enterprise certification or complete regulatory compliance.

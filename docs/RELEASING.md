# Releases and in-app updates

A Git push updates source code. A **published GitHub Release** makes a version available to the app.

## Routine patch

1. Make and review the changes; pass Windows checks.
2. Change `VERSION` in `source/appmeta.py` and the version in `pyproject.toml`. Update `CHANGELOG.md` and `docs/RELEASE_NOTES.md`.
3. Tag the reviewed commit, for example `git tag v0.2.1`, then `git push origin v0.2.1`.
4. The release workflow runs tests, builds the app/installer, generates checksums and creates a **draft release**.
5. Test the installer on a clean Windows machine and review the release assets. Publish the draft when accepted.
6. Installed apps detect the newer version at startup or when the user clicks ↻ Check updates. Downloads require user confirmation. Active work cannot be interrupted by an installation.

The workflow refuses to replace an existing release. Publish a new version rather than altering shipped binaries. Rollback should normally be a new higher patch version containing the previous known-good behavior; in-app downgrades are rejected.

## Signing

Initially, artifacts are unsigned and the app will not launch them automatically. SHA-256 proves download integrity, not publisher identity. Do not instruct users to bypass Windows security warnings.

For signed releases, configure a trusted code-signing service or an exportable code-signing certificate supported by your organization's policy. The supplied optional PFX integration uses repository secrets `SIGNING_PFX_BASE64` and `SIGNING_PFX_PASSWORD` and repository variable `SIGN_RELEASES=true`. It signs the app before installer creation, then signs the installer before checksums. Prefer a managed signing service where your certificate/key policy requires hardware-backed signing; adapt the signing step accordingly.

Never commit certificates or private keys. The updater accepts automatic installation only when both current app and new installer have valid signatures from the same certificate. The first signed version and certificate rotations require a manual transition.

## Assets

- `TitleVisionAssistant-Setup-X.Y.Z.exe` — interactive per-user Windows installer.
- `TitleVisionAssistant-Portable-X.Y.Z.zip` — complete folder bundle.
- `SHA256SUMS.txt` — release file hashes, generated after signing.
- `dependency-inventory.json` — dependency names/versions; not a certified SBOM.

GitHub's release API must return the installer's `sha256:` digest before the in-app client accepts a download. The feed is public; private feeds require a separate authentication design.

## Upgrade history

Version 0.2.0 introduces stable user data. Before the first operational run, use **Import previous history** to select the previous app's `data/history.sqlite3`. An adjacent legacy database is imported automatically only when the destination does not exist. Existing destination records are never overwritten. Keep a backup; conflicting histories need manual review. Future upgrades keep using the stable data folder.

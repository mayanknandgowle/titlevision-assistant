# Contributing

This project is source-visible with all rights reserved. Discuss contributions with the owner before starting substantial work; public visibility does not grant a general reuse license.

1. Open a minimal issue using synthetic data.
2. Keep changes focused and preserve preview/revalidation/verification safeguards.
3. Follow `docs/DEVELOPMENT.md` and run the offline suite.
4. Add regression coverage for real failure modes.
5. Update user-facing docs and release notes as needed.
6. Submit a pull request with behavior, validation and rollout risks.

Never include real order data, original client attachments, credentials, browser profiles, database backups or signing keys. Do not test writes on live orders as part of CI. A maintainer must explicitly coordinate any supervised production acceptance.

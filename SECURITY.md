# Security policy

## Report privately

Use [GitHub private vulnerability reporting](https://github.com/mayanknandgowle/titlevision-assistant/security/advisories/new). Do not create a public issue containing credentials, cookies, customer names, addresses, order records or history databases. If private reporting is unavailable, contact the repository owner through an existing approved channel without sending sensitive details publicly.

## Supported releases

Security fixes target the latest stable release. Earlier unversioned desktop copies should be migrated after an approved acceptance test. No response-time SLA or security certification is claimed.

## Data boundaries

The app automates actions in an operator's authenticated TitleVision session. It does not collect passwords. Browser profile data can authorize access and must be protected as sensitive. The local SQLite journal contains order metadata and comments: limit access through Windows user permissions, use your organization's endpoint protection policy, and apply an approved retention/backup policy.

Do not attach production screenshots, SQLite files, browser storage or credentials to issues, pull requests or release assets. Automated tests must use synthetic pages and isolated browser contexts.

## Update security

Updates come from one public GitHub repository over HTTPS. Download hosts, asset names, versions, sizes and hashes are validated. Valid matching Authenticode publisher signatures are required for automatic installer launch. The app does not silently execute unsigned updates. SHA-256 is an integrity check, not an independent proof that a publisher is trustworthy.

Protect repository access, require review for release changes and safeguard signing keys. A compromised same-user Windows account or compromised trusted publisher is outside what this updater can defend against. Do not embed GitHub tokens or signing secrets in the app.

## Known limits

Live SLA save acceptance and login restart validation remain outstanding. The app does not guarantee server-side exactly-once writes, encrypt its SQLite database independently, provide role-based access control, or reconcile uncertain saves automatically. It relies on the user's TitleVision permissions and Windows account boundary.

# Security

## What is protected, and how (all implemented and covered by automated tests)
| Area | Control |
|---|---|
| Accounts | Ordinary user accounts in the local database. Passwords hashed with PBKDF2-SHA256 (200,000 rounds, per-user salt). Minimum 8 characters (`MIN_USER_PASSWORD_LEN`). Created by the person on the page (`/auth/register`); the operator can reset a password with `python -m backend.users passwd NAME`. |
| Open access, one kind of user | **Anyone can use triage with no account.** Anyone can create a free account, which gives a private history that only that user can read. There are **no staff, health-worker, clinician or admin logins** in the web app. Ownership is enforced on the server: another person's record answers "not found", never "forbidden". Records saved without an account have no owner and are readable by nobody (they only expire under the retention rule). |
| Login protection | Account locks for 15 minutes after 5 failed attempts; login attempts rate-limited per address; unknown users take the same time as wrong passwords; every success/failure is audited. |
| Tokens | HMAC-signed, expire after 8 hours (`TOKEN_TTL_SECONDS`); tampered or expired tokens are rejected. |
| Rate limiting and limits | 60 patient requests/minute per address (`RATE_LIMIT_PER_MINUTE`), 2,000-character input, 1 MB request body, 300 KB PDF payload. |
| HTTP headers | `nosniff`, no framing, no referrer, locked-down browser permissions, no-store on account and history pages; in production also a strict Content-Security-Policy and HSTS (over HTTPS). |
| Errors and logs | No stack traces to clients. Access logs record method, path, status and timing only - **never patient text** (tested). |
| Audit log | Who did what to which record (ids only), kept in the database. |
| Production guard | With `ENV=production` the app **refuses to start** if `SECRET_KEY` is missing/short, CORS is `*`, login is off, the default database password is used, or PostgreSQL is configured but unreachable (it will not silently fall back to a local file). |
| Containers | App runs as an unprivileged user; health check on `/ready`. |
| Supply chain | CI runs the tests and the evaluation gate on every change (`.github/workflows/ci.yml`). |

## Who can do what
| Action | Anyone (no account) | Signed-in user |
|---|:-:|:-:|
| Use triage, download the PDF of the result in front of you | yes | yes |
| Keep a private history; list, open, download, delete your own results | | yes |
| Mark your own result right or wrong (feedback) | | yes |
| Change password, erase account and all your data | | yes |
| Read, change or delete anyone else's records | no | no |
| Statistics, audit log, purge, backups, password resets | operator only, from the server command line | |

## HTTPS on a clinic network (offline)
Passwords and tokens must not travel in clear text, even on a clinic Wi-Fi. Use the bundled proxy:
1. In `.env`: `ENV=production`, `TRUST_PROXY=true`, a strong `SECRET_KEY` (`python -c "import secrets;print(secrets.token_hex(32))"`), `CORS_ORIGINS=https://<your-hub-name>`, `SITE_ADDRESS=<your-hub-name>`, a strong `POSTGRES_PASSWORD`.
2. `docker compose --profile https up -d`, and do not publish port 8001 to the network (remove that `ports` line).
3. Caddy creates its own local certificate authority (`tls internal`). Copy its root certificate (`docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt .`) to each tablet/phone and install it once as a trusted certificate; the browser then shows a normal padlock.

## Not covered / known limits - please read
* **Not independently audited.** No penetration test, no load test, no formal threat-model review has been done. Commission one before any public deployment.
* **Tested here:** unit/API/PostgreSQL tests and a real production-mode server over HTTP. **Not tested here:** the Docker image build, the Caddy HTTPS profile and the CI workflow (written and syntax-checked only) - test them on your hardware.
* **Tokens cannot be revoked early.** Disabling an account stops new logins but an already-issued token works until it expires. To cut off everyone immediately, change `SECRET_KEY` and restart. Keep `TOKEN_TTL_SECONDS` short on shared devices.
* **No two-factor authentication, and no password recovery by email** (by design: no email/phone is collected). The operator can reset a password from the command line.
* **Open registration** lets anyone create accounts; it is rate-limited per address (20 per hour) and can be closed with `REGISTRATION_OPEN=false`. Every account can only read its own records, so a malicious account gains nothing beyond its own history.
* **Rate limiting is in memory**: it resets on restart and is per instance (fine for one clinic hub).
* **Patient text is sensitive data.** Stored sessions (and backups) contain what patients typed. Protect the disk (BitLocker/LUKS), the database, and the backup copies; the app does not encrypt fields itself.
* **The audit log is not tamper-proof** against someone with direct database access.
* The single-file web page needs inline scripts, so the CSP allows `'unsafe-inline'`.
* The knowledge content is draft and not clinician-reviewed - that is a safety issue, not a security one, but it is the largest risk (see `PRODUCTION_READINESS.md`).

## Reporting a vulnerability
Tell the project maintainers privately (do not post details publicly) and give them time to fix it before disclosure.

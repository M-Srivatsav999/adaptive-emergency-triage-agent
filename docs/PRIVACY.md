# Privacy and data handling

*This describes how the software behaves. It is not legal advice; have your college or a lawyer confirm what the law requires where you deploy (in India, health data is covered by data-protection law).*

## What data exists
| Data | Where | Why | How long |
|---|---|---|---|
| What the patient types and answers, the result, the reasoning trace | Local database (PostgreSQL or SQLite) on the server computer | Safety review, clinician feedback, regenerating the PDF | `RETENTION_DAYS` (default 90), then deleted automatically; `0` = keep forever; `STORE_SESSIONS=false` = save nothing |
| User accounts (username, password hash) | Same database | Private history | Until the user erases the account (or the operator disables it) |
| Audit log (who did what to which record id) | Same database | Accountability | Kept (contains no patient text) |
| Server logs | Console / Docker logs | Operations | Method, path, status, timing only - **no patient text, no names** |
| Backups | `backups/` | Recovery | Keep the newest 14 (`prune`); **they contain patient text** - protect and delete them accordingly |

## Who can see what
| Who | Sees |
|---|---|
| A signed-in ordinary user | Only the results saved under their own account |
| Someone using the tool without an account | Their result on screen and its PDF; if saving is on, the record is kept **without an owner**, nobody can open it, and it is deleted when it expires |
| Anyone else (including the people who run the service) | Nothing through the app: there is no screen or endpoint that lists other people's results. The operator can reach the database directly, so protect it (see good practice) |

An ordinary user can delete a single result, or **erase their whole account and all their saved results** from the page. Tell users not to use their real name as a username.

## What the software does NOT do
No internet calls with patient data, no analytics, no advertising, no sharing. The local AI model runs on the same machine. The page asks users not to type names, phone numbers or addresses.

## Patient-facing notice
A one-time notice appears on first use (tablet or phone) explaining: general guidance only, not a doctor, get emergency help if very ill, what is saved and for how long, and that deletion can be requested. The retention figure comes from the running system.

## Rights and deletion
A user can delete any of their own records (`DELETE /history/{id}` or the History window); deletions are audited. Feedback attached to a record is deleted with it. Backups are not edited - they age out through `prune`.

## Good practice for the clinic
Keep the hub in a locked room with disk encryption; never share accounts; keep backups on an encrypted or locked-away drive; tell patients what is saved; do not export records to personal phones or messaging apps.

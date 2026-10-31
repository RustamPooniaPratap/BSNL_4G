# Alert & Email Automation

Administration › **Alert** (Admin only, in the menu and in the API: every `/api/alerts/` endpoint requires the Admin role).

| Page | Purpose |
|---|---|
| Email Setup | The one outgoing SMTP account: Save, Test Connection, Send Test Email, Activate/Deactivate. |
| Automations | Five templates (CSV Arrival Reminder, RCA Submission Reminder, Automatic Uptime Report, Upload Failure Alert, Custom Scheduled Email), configured in six steps with a live preview. |
| Email History | Every prepared email, its attempts and the SMTP server's response; Retry (failed) and Resend (as a new record). |

## Rules the module enforces

- The SMTP password is encrypted (Fernet) and never returned to the browser or logged. Leaving it blank keeps the stored one.
- Nothing is sent automatically until a test email has succeeded **and** the account is activated. Changing host, port, security, username or password deactivates the account until it is tested again; deactivating it pauses every automation.
- Statuses are *Queued*, *Processing*, *Accepted by SMTP* and *Failed*. "Accepted" means the mail server took the message; the portal does not know whether it reached the mailbox.
- Every scheduled run has a unique key (automation + slot), so a restart or a second worker cannot send a run twice. A message still *Processing* when the worker stopped is marked Failed (never resent blindly); use Retry after checking it.
- Failed sends are retried automatically twice (after 5 and 15 minutes), then left for an Admin.
- RCA reminders cover circle uploads only. CSV/RCA reminders go to the CI users granted that project-circle (Organization › User Access) plus the configured recipients.
- Attachments are the portal's own reports (xlsx/csv) and one optional Admin-uploaded file (≤ 10 MB). "Relevant report per recipient" limits each portal user's attachment to their own circles. The full RCA master is never sent per recipient.

## Deployment

1. Install requirements (`cryptography` was added): `pip install -r backend/requirements.txt`
2. Apply migrations: `python manage.py migrate` (adds the `alerts` tables only).
3. Environment (set on the server, never in Git):
   - `ALERT_ENCRYPTION_KEY`: a Fernet key (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). Optional; without it the key is derived from `SECRET_KEY`. If either key changes, re-enter the SMTP password.
   - `PORTAL_URL`: the address used by the "Open Reporting Portal" button (default `http://localhost:5173`).
4. Start the worker, **one** instance, next to the web server:
   - Continuous: `python manage.py run_alerts` (checks every 30 s; `--interval N` to change).
   - Or from Windows Task Scheduler / cron every minute: `python manage.py run_alerts --once`.
   - Run it as a service (NSSM, a scheduled task "at startup", or systemd) so it restarts after a reboot. The pages show a warning when the worker has not reported for a few minutes; schedules and Run Now wait until it runs.

## Needs approval from company IT

- **How the server may send mail.** Microsoft 365 often disables SMTP AUTH (basic username/password). Options: enable SMTP AUTH for one dedicated mailbox, or an internal SMTP relay / M365 connector that accepts this server's IP without a password. The portal does not support OAuth sending.
- The sender mailbox and display name, and whether it may send to external (non-company) addresses.
- Firewall: outbound access from the portal server to the SMTP host on port 587 (STARTTLS) or 465 (SSL), or 25 for an internal relay.
- SPF/DKIM alignment for the sender domain if a relay is used, so mail is not marked as spam.
- Approval to send reports with site data by email, especially to external recipients.

## Tests

`backend/tests/test_alert_automation.py` (SMTP is mocked; no real mail is sent) and `frontend/src/pages/alerts/AlertPages.test.tsx`.

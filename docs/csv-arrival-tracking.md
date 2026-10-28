# CSV arrival tracking (frontend only)

Route `/daily-ingestion` (sidebar: **CSV Arrival & Follow-up → CSV Arrival Tracking**, formerly "Raw CSV files"). It tracks whether each circle has sent its daily 4G / LWE raw CSV for a reporting date, and records contacts and follow-ups. Uploading and checking a CSV is a separate page, `/data/upload-csv`.

**Storage:** everything is held in browser memory (`TrackingProvider`, mounted in `App.tsx`). It is kept while you move between pages and **lost on refresh**. Nothing is sent to the server or written to the database, the workbook or browser storage.

## Data

| Data | Source |
|---|---|
| Requirements (circle × report type) | Master workbook via `GET /api/dashboard/filters/`. Only pairs with sites are required: 4G for MP, OD, RJ; LWE for AP, BH, CG, JH, MH, MP, OD, TL, UP, WB (13). |
| Arrivals, contacts, follow-ups, deadlines | Entered by users on this page; all start empty. |
| Files on the server | `GET /api/raw-files/` (read-only). Shown for reference and offered as file-name suggestions; never used to mark a circle as received. |

**Layout:**
- **Header card:** "CSV Arrival & Follow-up", with an email-mode chip on the right:
  - "Email: test mode · not delivered" with the console backend;
  - "Email: live · <transport>" with a real backend;
  - "Email unavailable" when the status cannot be read.
- **Toolbar:**
  - The reporting date on the left, with the weekday shown in words.
  - The **Email** group: **Send reminder** opens the date's pending reports, and choosing one opens the usual reminder confirmation. **Compose email** opens the composer.
  - **Deadlines** (outline button) and **Record arrival** (primary button).
- **Summary cards** (which filter the table) sit above the circle-wise submissions table. The highlight cards (pending circles, late submissions, recently received, missing contacts and the submission timeline) were removed on 23 Oct 2026. The summary cards and table filters cover the same information.

The workbook's IE/CI phone columns are deliberately not read (personal data, and they belong to site engineers, not report submitters), so contacts start blank.

## Status rules (`lib/tracking.ts`, `buildSubmissions`)

| Status | Rule |
|---|---|
| Received | An arrival record exists and its details are complete and consistent |
| Needs review | An arrival record exists but: no file name, a file name not ending in `.csv`, an arrival in the future, or an arrival before the reporting date |
| Late | No arrival record and a **configured** deadline has passed |
| Pending | No arrival record, and the deadline has not passed or none is configured |

- **Deadlines** are set per report type in **Deadlines**: due on the reporting date, the next day or the day after, at a set time. With no deadline nothing is ever Late.
- **Arrived after the deadline:** an arrival recorded after its deadline is still Received, labelled "after deadline".
- **Contacts never change the status.** "Missing contact details" means no name, or a name with neither phone nor email.

## Recording

- **Arrival:**
  - The actual arrival date and time are required and cannot be in the future.
  - "It arrived just now" fills in the current time and labels it **time of entry**.
  - One arrival per circle, report type and reporting date; a second one is refused, and the existing record can be edited or removed instead.
- **Contact:** per circle and report type. Every field is optional: name, designation, phone (10–15 digits), email, backup and notes. A name is required only when other details are given.
- **Follow-up:** date and time (not in the future), method (Call, Email, Message, Other), outcome, and optionally the contact person, expected submission and next follow-up. No contact is required, and nothing is sent.

## Email

The first part of the page that talks to the backend. Sending goes through one shared service, `apps/common/email.py` (`send_email`), so the planned automatic reminders can reuse it.

- **Send reminder now** (bell icon on pending and late rows, and "Send reminder now" in a row's details):
  - The backend builds the standard reminder from the circle, report type and reporting date, and checks that the pair exists in the Master workbook.
  - It mentions a deadline only when one is configured.
  - The panel shows the recipient and the full text before anything is sent.
  - The recipient is the email address in the circle's recorded contact. Without one, sending is disabled and the panel offers to add it. No address is ever guessed.
  - The same reminder to the same To recipients is refused for 2 minutes (HTTP 409). This guards against double clicks, and will guard the future automatic job.
- **Compose email** (page header, or "Compose email" in a row's details):
  - Fields: To, CC (optional), Subject, Message.
  - From a row, "Load standard reminder" fills in the reminder text for editing.
  - "Review email" validates the fields and shows a preview. Only **Send email** sends.
  - Cancel and closing the panel never send.
  - The backend validates every field again: up to 20 valid addresses, a single-line subject of at most 200 characters, and a message of at most 20,000 characters.
- **Results:**
  - The backend's own message is shown.
  - In test mode the result reads "Printed in the backend terminal (test mode)", never "sent" or "delivered".
  - Transport failures show "Not sent", with no internal error detail.
- **Test mode** (current):
  - `EMAIL_BACKEND` defaults to Django's console backend, so emails are printed in the Django terminal and nothing leaves the machine.
  - The page shows "Email: test mode", and each email panel shows a TEST MODE banner.
- **Live sending** is not available yet:
  - It needs a real backend in `EMAIL_BACKEND`. A Microsoft Graph backend for the company Microsoft 365 mailbox is planned and not implemented.
  - It also needs sign-in, which the portal does not have. With a non-local backend, both endpoints refuse with 403 (`sign_in_required`).
- **Automatic reminders** do not exist: there is no scheduler. `email/status/` reports `automatic_reminders: false`.

Endpoints (under `/api/email/`):

| Endpoint | Purpose |
|---|---|
| `status/` (GET) | test mode or live, the sender |
| `reminder-template/` (GET: circle, report_type, reporting_date, deadline?) | the standard reminder's subject and body |
| `reminder/` (POST: circle, report_type, reporting_date, deadline?, to, cc?) | send the standard reminder (text built on the server) |
| `send/` (POST: to, cc?, subject, body) | send a personal email |

## Open points

1. Submission deadlines per report type (none configured by default).
2. Whether revised or second files for the same date should be allowed. They are currently refused; edit the existing record instead.
3. Who the submitting contacts are for each circle.
4. Persistence: a backend API and database table for arrivals, contacts and follow-ups.
5. Email:
   - Microsoft Graph backend and its mailbox.
   - Portal sign-in, needed before any live sending.
   - The wording of the standard reminder (a proposal in `reminder_content`).
   - Whether a sent email should be logged as a follow-up.
   - Automatic reminder rules: who receives them and when.

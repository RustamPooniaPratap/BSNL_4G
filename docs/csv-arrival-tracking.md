# CSV arrival tracking

Route `/daily-ingestion` (sidebar: **CSV Arrival & Follow-up → CSV Arrival Tracking**, Admins only). For each project and circle on a reporting date it shows two separate facts, both read from PostgreSQL:

1. **Stored daily data:** whether the daily-performance table holds usable records for the date, and how complete they are. It doesn't matter which import wrote them, the Master workbook import or a raw CSV upload.
2. **CSV upload:** whether a raw daily CSV was uploaded for the date, and where it is in its lifecycle.

It also keeps contacts, follow-ups, deadlines and manual arrival notes. Uploading and checking a CSV is a separate page, `/data/upload-csv`.

**Why the page used to show "Pending" for every circle (fixed 29 Oct 2026):** the status was computed in the browser from manually recorded arrivals only (`TrackingProvider`). The page never queried the daily-performance table or the raw-upload history, so every date read as Pending. Data existed for all 13 project circles on 1–20 Oct (Master workbook), and for 4G OD and RJ on 25–27 Oct (raw CSV uploads).

## Data

| Data | Source |
|---|---|
| Project circles (rows) | The site master in PostgreSQL (`UptimeSite`), within the user's circles (`accounts.scope`). Today that is 4G for MP, OD, RJ; LWE for AP, BH, CG, JH, MH, MP, OD, TL, UP, WB. |
| Stored daily data | `SiteDailyPerformance` joined to `UptimeSite`, computed on every request by `GET /api/arrival-tracker/` (`apps/uptimedb/arrivals.py`) |
| CSV uploads | `DataImportBatch` of kind `raw_daily_csv` for the project, circle and reporting date |
| Contacts, follow-ups, deadlines, manual arrival notes | Entered on this page; held in browser memory only (`TrackingProvider`) and lost on refresh. They never change the status. |
| Files on the server | `GET /api/raw-files/` (read-only, for reference; never marks anything as received) |

### `GET /api/arrival-tracker/?date=YYYY-MM-DD[&start=&end=]` (Admins; read only)

Per project/circle (fields in `TrackerItem`, `types/rawUpload.ts`):

- **Expected sites:** the master's On-Air sites (`On-Air = Yes`), the dashboard's default scope (business-rules.md, "Scopes"). The total master sites are shown alongside. Sites that are not On-Air are never expected.
- **Usable record:** outage minutes recorded and between 0 and 1,440. NULL is "not reported". Values outside that range are counted as invalid and never as usable.
- **Coverage:** usable records of expected sites ÷ expected sites; missing = expected − usable − invalid.
- **Data state:**
  - complete: every expected site has a usable record;
  - partial: some do;
  - none: no expected site does;
  - no_scope: the master has no On-Air site for the pair. Its observed records are still shown.
- **Data source:** the import that last wrote each usable record (`batch.kind`): Master workbook, raw CSV, or both, with counts.
- **Latest data date / latest complete date:** the latest stored reporting date with any usable record / with every expected site, computed from the stored dates, never from upload times or today's date.
- **Uploads for the date:** every raw upload with its file name, upload time, uploader, records ready or imported, rejected rows and error. **Upload state** is the most advanced one: imported > awaiting confirmation > validated with nothing new > blocked > failed > discarded > none.
- **Latest CSV received / imported:** the latest reporting date of a non-discarded / committed upload.
- **Range:** usable records and state per day, from `start` to `end`. The default is the 14 days ending on the date, and the maximum is 92 days.

Completeness is measured against the master's **current** On-Air sites: the master has no dated On-Air history.

## Status rules (`lib/tracking.ts`, `trackStatus`)

| Status | Rule |
|---|---|
| Data complete | Stored data covers every expected site (whether or not a CSV was uploaded) |
| Partial data | Stored data covers some expected sites |
| File received · no usable data | No usable data, but an upload is recorded: awaiting confirmation, nothing new, blocked, failed, or imported without usable records |
| No data · past deadline | No usable data, no upload (a discarded upload doesn't count), and a **configured** deadline has passed |
| No data available | No usable data and no upload, and no deadline has passed or none is configured |

The CSV upload state is always shown in its own column ("CSV imported", "Validated · awaiting confirmation", "CSV blocked", "No CSV upload recorded" and so on). A complete date with no upload reads **Data complete / No CSV upload recorded**. The page never calls a date "CSV imported" just because data exists.

- **Deadlines** are set per report type in **Deadlines** (held in the browser): due on the reporting date, the next day or the day after, at a set time. Without a deadline nothing is ever late, and stored data is never late.
- **Contacts and manual notes never change the status.** "Missing contact details" means no name, or a name with neither phone nor email.
- **Refreshing:** the page asks the server again whenever the date, the range or the active data version changes, and on **Refresh**. While a new date loads, the previous date's rows are hidden. Each visit to the page fetches fresh figures, so a commit on Upload CSV is visible on the next visit.
- **Layout:**
  - Filters: date, search (circle, contact, file, uploader), circle, project, status, contact, "Incomplete only".
  - Summary cards: project circles, data complete, partial, no usable data, CSV uploads recorded, past deadline, missing contacts.
  - The table: data status and source, coverage, CSV upload, latest dates, deadline, contact, last follow-up.
  - **Daily coverage** grid for the range: select a day to open it.
  - The details panel lists the stored data, every upload for the date, the contact, follow-ups and any manual note.

## Recording

- **Manual arrival note** (in a row's details): for a file received outside the portal, for example by email.
  - The actual arrival date and time are required and cannot be in the future.
  - "It arrived just now" fills in the current time and labels it **time of entry**.
  - One note per circle, report type and reporting date.
  - A note is held in the browser only and never changes the status.
- **Contact:** per circle and report type. Every field is optional: name, designation, phone (10–15 digits), email, backup and notes. A name is required only when other details are given.
- **Follow-up:** date and time (not in the future), method (Call, Email, Message, Other), outcome, and optionally the contact person, expected submission and next follow-up. No contact is required, and nothing is sent.

## Email

The first part of the page that talks to the backend. Sending goes through one shared service, `apps/common/email.py` (`send_email`), so the planned automatic reminders can reuse it.

- **Send reminder now** (bell icon on rows with no stored data and no upload, and "Send reminder now" in a row's details):
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

1. Submission deadlines per report type (none configured by default). Deadlines are still held in the browser.
2. Which project circles must send a daily CSV. Today every master pair is listed. LWE raw files cannot be imported until the LWE ID mapping is supplied, so LWE uploads can be received but never imported.
3. Who the submitting contacts are for each circle.
4. Persistence for contacts, follow-ups, deadlines and manual notes (a backend table). The data and upload status are already read from the database.
5. Whether completeness should use a dated On-Air history, if one is ever kept. Today it uses the master's current On-Air flag.
6. Email:
   - Microsoft Graph backend and its mailbox.
   - Portal sign-in, needed before any live sending.
   - The wording of the standard reminder (a proposal in `reminder_content`).
   - Whether a sent email should be logged as a follow-up.
   - Automatic reminder rules: who receives them and when.

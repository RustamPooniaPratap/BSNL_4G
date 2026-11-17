# BSNL Module: Auto Email Reports and BSNL Letters

Reproduces the "Auto email reports" and "BSNL letters" pages of the reference report
`Data/reference/4G_KPI_Report (2) 6.html` on the portal's own data. React pages: `/bsnl/auto-email-reports` and
`/bsnl/letters` (sidebar group "BSNL Module"). API: `/api/bsnl/` (see `urls.py`).

## Data sources (decisions of 17 Nov 2026)

The reference works on an outage dump with start/end timestamps, per-category SLA targets and four responsibility
buckets. The portal holds none of those, so:

| Reference | Portal source |
|---|---|
| Sites, Circle, Cluster, NE, category | `sitedata.Site` (Cluster = CI name, NE = IE name, category = project 4G Saturation / LWE) |
| Uptime, SLA, USD | `apps.dashboard.metrics` on the daily records (On-Air population, pooled uptime, NSLA < 98.5%, USD = sites with outage) |
| Outages for letters | `rca.RcaRecord` (one site-day each; duration is displayed as whole outage minutes) |
| RCA bucket | approved Final Bucket (`rca.taxonomy`) -> `RcaBucketMapping` (BSNL OFC and BSNL Media = Customer; blank/unapproved = Pending) |
| Ticket | matching `tickets.Ticket` (same site and outage date) |
| Distribution Master, BSNL contacts, sender | new: `DistributionRecipient`, `CircleLetterProfile` |

Not reproducible without outage timestamps: Sites down now, MTTR, longest outage, long-down sites, repeat offenders.
Circles/CIs are ranked by NSLA share (portal rule) instead of the reference score. Letters have no planned-outage
exclusion (RCA records carry no planned flag) and no open-ended outages (each record is one day). D-1 is the latest
reporting date of the uptime data (its Complete / Provisional status is shown, rule B-7); for letters, the latest RCA
reporting date.

All BSNL Module reports, letters and exports display outage duration as whole, comma-formatted Outage Minutes.
Aggregates sum the underlying minute values before rounding; legacy hour-valued API fields remain for compatibility.

## Workflow and safeguards

- Letters: Draft (edit, regenerate) -> Approved -> Sent -> Acknowledged -> Exclusion accepted / rejected; an Approved
  letter can return to Draft. Every change is a `LetterEvent` (append-only). Reference numbers `CODE/BSNL/YYYYMM/NNN`
  come from `LetterSequence` under a row lock. The generated letter is kept; edits are stored separately and sanitised.
- Downloads (.eml, Excel, Word, print) never send and never change a status.
- Sending uses the one Alert email account and only when the server sets `BSNL_EMAIL_SEND_ENABLED=true`.
- Schedule: Daily D-1 09:00 IST, Weekly Monday 10:00 IST, run by the existing worker (`manage.py run_alerts`, which
  calls `scheduler.tick`). Off until switched on in the page (Setting `bsnl.auto_reports`); each period and circle is
  sent once (`ReportRun.slot_key`).

## Permissions (Users & Roles)

`bsnl_reports`: view, send, manage (recipients and schedule). `bsnl_letters`: view, edit, approve, send, manage
(contacts, sender, letter recipients, bucket mapping). Admin: everything. NOC Lead: view both, edit letters. CI and
custom roles: only what is granted, on their assigned project/circle pairs. Creating, approving or sending a Circle's
letter or email needs the permission on every project of the circle (or one chosen category); All India needs all.

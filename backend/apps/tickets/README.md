# Ticket Management

The module stores OFC outage tickets and their import, status, audit, and notification history. Site identity stays in
`apps.sitedata.Site`; every ticket must resolve to a dashboard-scope Site and an active Organization project/circle
association before import. Ticket visibility and upload permissions are checked against the existing project/circle
assignment system.

An outage is matched only by the normalized master `Site.site_key`, the workbook `Date`, and the parsed
`Actual Down Time` timestamp (to the workbook's second precision). That triple is protected by a database unique
constraint. Duplicate triples inside one workbook are all rejected; if legacy or concurrent data ever produces more
than one match, the importer reports the ambiguity instead of selecting a ticket. The reference workbook contains one
reserved example row; its exact values are shown as skipped in preview and never create a ticket or send email.

Excel imports are previewed before commit. The same committed file hash requires explicit confirmation before it is
processed again. Manual and Excel status transitions are append-only `TicketEvent` records; notification attempts are
stored separately so a mail failure cannot roll back a ticket.

An Open row creates a ticket when no outage key matches, updates a matching Open ticket, or reopens a matching Closed
ticket. A new Closed row is skipped. Existing tickets are matched by the canonical Site key, workbook date and
Actual Down Time normalized to local second precision; an ambiguous key is rejected rather than guessed. The raw
values from each workbook row are retained in the ticket and event history.

Each created, updated-Open or reopened ticket queues a separate message to that row's Email ID. The recipient is a
field technician or partner contact, not a portal user: no account is created for that address, and the email is
informational only, with no portal link, credentials, token or closure action. Closure is done only by an authenticated
user holding the ticket's Close permission. The layout is in `email_templates/` and rendered by `email_content.py`,
separately from sending (`services.send_notification`). “Accepted” means the
configured SMTP service accepted the message, not that the recipient received it. A failed send is recorded without
rolling back the import and may be retried by a user with the ticket's Retry permission. Manual closure requires a
reason; reopening requires a reason and sends a new message.

The ticket list (`GET /api/tickets/`) takes `status=Open|Closed|All` and lists Open tickets when no status is given;
search, circle, vendor, date and status filters combine. The Ticket Dashboard shows overall KPI cards (unfiltered)
and an Open-by-default ticket table with a Close action for permitted users. The All Tickets page sends `status=All`.

The endpoints are under `/api/tickets/`. The React module is available at `/tickets`, `/tickets/all`,
`/tickets/upload` and `/tickets/<id>`. CI system-role ticket grants are seeded by the accounts migration; custom
roles require explicit Ticket Management permissions and project/circle assignments.

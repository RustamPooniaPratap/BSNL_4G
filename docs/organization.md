# Organization (Administration › Organization)

Admins manage the application's projects, circles, the circles each project covers, how source files write circle
codes, and which projects and circles each CI user may use. Backend: `apps.organization`. Frontend:
`pages/OrganizationPage.tsx` (one sidebar entry, six tabs).

| Tab | URL | What it manages |
|---|---|---|
| Projects | `/admin/organization` | `Project`: stored identifier (`key`, fixed), short code, name, description, active |
| Circles | `…/circles` | `Circle`: one global record per circle; code fixed, name editable; records per project |
| Project-Circle Mapping | `…/mapping` | `ProjectCircle` (unique per project and circle), active, removable only while unused |
| User Access | `…/access` | `UserCircleAccess`: CI grants per project **and** circle |
| Code Mapping | `…/code-mapping` | `CircleAlias`: a source's circle code or name → canonical circle |
| Change History | `…/history` | `OrganizationChange`: who, when, before → after, reason (read only) |

## Identity and separation

- Data tables keep storing the project key (`"4G Saturation"`, `"LWE"`) and the circle code (`"MP"`) as text. The key and
  code therefore cannot change; names can. Projects are deactivated, never deleted; a circle can be deleted only while unused.
- A site is `(project, circle, site ID)` (`uptime_site_identity`). Daily values are unique per site and date, and monthly
  values per site and month, so MP 4G and MP LWE never share a site, a value or a count. The same site ID text may exist
  in both projects.
- Raw uploads keep project, circle and reporting date. The "already imported" notice only matches the same project,
  circle and date. Site IDs resolve only within the selected project and circle (`raw/resolvers.py`).
- An association is membership only. It creates no sites, data, reporting obligation, access or RCA records.

## Changes, removal and deletion

- Every write runs in one database transaction together with its Change History entry. A refused or failed operation
  changes nothing and records nothing.
- **Remove** (association) and **Delete** (circle) open a confirmation dialog. The Admin must type the exact identity
  (`AP - 4G Saturation`, or `KL - Kerala`) before one request is sent. The server checks permissions and dependencies
  again.
- **Removing an association:**
  - When nothing refers to it, only that project's association is deleted. The circle and its other projects stay.
  - When sites, values, uploads, RCA records or expected units, escalation sites or user grants refer to it, it is kept
    and deactivated instead. Nothing is cascaded, and the answer says which records blocked the removal.
- **Deleting a circle** is possible only when it has no association, code mapping, record of any project, grant or
  legacy assignment. Otherwise, deactivate it.
- **Database readiness:** an association needs no new table, column or migration. Sites (from the Master workbook), then daily, monthly and upload records, go into the existing project-scoped tables.

## Where it is used

- **Upload CSV** (`raw_views`): offers active projects, then each project's active circles within the user's grants.
  Submissions must be an active association, and the user must be granted that project and circle.
- **Exports** (`report_export.resolve_scope`): limited by project and circle together.
- **CSV Arrival** (`arrivals`): an association without master sites shows as "no scope", with no obligation.
- **RCA** manual records and expected units (`rca.views`, `rca.cycles`): must be active associations.
- **Master workbook import** (`uptimedb.importer`): the preview reports unknown circles and pairs that are not
  associated. A full import is refused until an Admin sets them up. A daily-values-only import writes to existing sites
  only.
- **Circle aliases**: raw CSV, Master workbook (database import), day-wise report, escalation matrix and RCA workbook are
  all read through `AliasResolver`. Lookup order: project alias, then source-wide alias, then the canonical code. An
  unknown code is reported; it never becomes a circle.
- **Dashboard filter options** (`/api/dashboard/filters/`, used by the dashboards, Portfolio and
  both Excel downloads):
  - Data circles plus every active association. A circle without data is labelled "(no data yet)", and selecting it
    reports nothing, never zeros.
  - Circles with records stay listed for historical reporting after their association is removed.
  - Chart series come from data only (`data_report_types`).
- **Selectors** (`hooks/useOrganization`): Users & Roles, Upload CSV, the RCA register form and the Portfolio project
  order. Components that stay mounted reload the catalog after any Organization change; other pages fetch on opening.

## Access

- Admins and NOC Leads are not limited.
- A CI user's access is the set of granted (project, circle) pairs. MP under 4G does not include MP under LWE, and a
  new association grants nothing.
- Legacy circle-only assignments (`AccountProfile.circles`):
  - The migration converted those whose circle belongs to one project.
  - The others keep their previous effect (every project of the circle) and are flagged "needs review" until an Admin
    chooses the projects.
- Users & Roles and User Access use the same grants and the same editor.

## Not covered

- The Excel-mode workbook loader (`dashboard/workbook.py`) keeps its built-in `Madhya Pradesh`/`Odisha` aliases. They
  match the seeded Master-workbook mappings.
- LWE site-identifier mapping (raw ID → master LWE site) is not configured. It is not managed here.

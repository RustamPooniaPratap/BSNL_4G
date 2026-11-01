# User Management & Project/Circle Access Control

Administration › **Users & Roles** (Admin only): Users · Roles & Permissions · Access Assignments (with Access Preview) · Access History.

## Model

`User → account role → assignments (role × project × circle) → (module, action) → data`

| Table (app `accounts`) | Purpose |
|---|---|
| `Role` | Built-in Admin / NOC Lead / CI (`system_key`, read only) and custom roles. |
| `RolePermission` | (module, action) grants of a role. A new role has none. |
| `AccessAssignment` | user + role + `organization.Project` + optional `organization.ProjectCircle` (empty = entire project), status, optional `valid_until`. One row per circle; unique per user/role/scope. |
| `AccessEvent` | Access history: actor, user/role, action, scope, details. Never passwords or tokens. |

Projects, circles and associations come only from Organization. The former `organization.UserCircleAccess` grants were copied into `AccessAssignment` (CI role) and the table was dropped; Organization › User Access edits the same CI-role assignments through `accounts.scope.set_pairs`.

## Account roles

- **Admin**: every page, project and circle, plus administration. Never granted through an assignment.
- **NOC Lead**: the CI permissions on every project and circle, and RCA workbook uploads (unchanged).
- **CI** and **Assigned access only**: rights come only from assignments. Without one: no data.

## Permission catalogue (`apps/accounts/catalog.py`)

| Module | Actions | Enforced by |
|---|---|---|
| Dashboard & Uptime | View, Export | every `/api/dashboard/*` data endpoint (restricted dataset, `apps/dashboard/scope.py`), daily/consolidated exports |
| Master Data | View, Export | `/api/master-data/*` |
| CSV Upload | Upload | `/api/raw-uploads/*` (options, preview, commit, own list) |
| RCA Register | View, Create, Edit | `/api/rca/records*`, workflow, comments |
| RCA Upload | Upload | circle RCA preview/commit, own uploads (no register or summary access) |
| RCA Summary | View | `/api/rca/summary/` and its options |

Admin only, not grantable: Team Performance, CSV Arrival Tracking, Data Source, RCA Submissions and cause mappings, consolidated RCA upload (group on Users), Organization, Users & Roles, Alert.

## Resolution rules (`apps/accounts/access.py`)

1. Signed in and active; a temporary password must be changed first.
2. An assignment applies only if active, not past `valid_until`, its role and project are active, and (circle assignment) its association and circle are active.
3. A permission holds on a project/circle pair when an applying assignment covering that pair grants it. Pairs never mix: a project-wide View gives no Upload/Export; a circle editor adds rights to that circle only.
4. **Entire project** covers every circle associated with the project in Organization, **including circles associated later**. Use selected circles to restrict.
5. Data whose project/circle is not associated in Organization is never in a restricted user's scope.
6. No deny rules: to restrict, deactivate or revoke the assignment that grants too much.
7. Results are computed per request: changes apply on the next request.
8. Admins cannot change their own role or assignments; custom roles hold only catalogue permissions.

## Deployment

```
pip install -r backend/requirements.txt
python manage.py migrate            # accounts.0006_access_control, organization.0003_access_moved_to_assignments
```

After deploying, give each CI user their projects and circles on Access Assignments (or Organization › User Access). **CI users without an assignment no longer see dashboards or the RCA register** (before, they saw every circle's dashboard data).

## Rollback

`python manage.py migrate organization 0002 && python manage.py migrate accounts 0005` recreates `UserCircleAccess`, copies active CI circle assignments back into it, then drops the new tables. Custom roles, other assignments and access history are lost on rollback; export them first if needed. Restore the previous code with the migrations reversed.

## Data Panel (Master Data) editing

Each dataset of `apps/masterdata/datasets.py` is its own permission module, `data_<dataset>`, with **View, Add, Edit and
Export** (independent; there is no Delete anywhere). Admin has all four on every dataset; NOC Lead and the built-in CI role
keep View and Export only (converted one-for-one from the former `master_data` grants by `accounts.0007`); everyone else
gets exactly what their roles grant, within their assigned projects and circles.

- Save: `POST /api/master-data/<dataset>/save/` with `{changes: [{id, values}], additions: [{values}]}`. All rows are
  validated and written in one transaction, or nothing is (errors come back per row and column).
- Rules per dataset: `apps/masterdata/editors.py` (editable columns, identity columns for new rows, derived keys,
  ranges, Organization associations). Model validation adds types, lengths and unique constraints.
- Provenance: Site Master, daily and monthly rows written by a save point to a new import batch of kind
  `data_panel`; escalation rows to an escalation batch with `initiated_via = data_panel`; RCA edits add an `RcaEvent`.
  The dashboard's database cache refreshes after every save.
- New dataset: register it in `DATASETS` (it gets View / Add / Edit / Export on Users & Roles automatically) and add an
  `Editor` to `EDITORS` to make it editable; without one it stays read-only.

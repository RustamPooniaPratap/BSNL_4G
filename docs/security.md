# Sign-in, roles and security

## Architecture

- **Sessions:** Django server-side sessions in the `django_session` table, using Django's own users, groups and password hashing. There is no second password store and no tokens.
  - The session cookie is **HttpOnly**.
  - The frontend never stores a session ID, password or token in `localStorage` or `sessionStorage`.
- **CSRF:**
  - `GET /api/auth/csrf/` sets the CSRF cookie and returns the token. The app keeps the token in memory and sends it as `X-CSRFToken` on every POST, PATCH or DELETE.
  - Sign-in is CSRF-protected even though the caller is anonymous.
  - Requests from the Vite origin pass Django's origin check through `CSRF_TRUSTED_ORIGINS`.
- **CORS:** credentialed requests are allowed only from `CORS_ALLOWED_ORIGINS` (default: the Vite dev server).
- **Session lifetime:**
  - Sign-in renews the session key (`login()`), and sign-out deletes the session on the server (`logout()`).
  - Sessions end after `SESSION_IDLE_MINUTES` (default 30) without a request, and when the browser closes.
- **Deny by default:** every API endpoint requires a signed-in, active user with a portal role (`IsPortalUser`). Only these opt out:
  - `GET /api/health/` (liveness only, no data);
  - `csrf/` and `login/`.

  Signed-out requests get **401**, and a role without access gets **403**.
- **Temporary passwords:** accounts created or reset by an Admin get a random temporary password and `must_change_password`. Until it is changed, the API answers 403 `password_change_required`, and the app opens *Set your password*.
- **Code:** `backend/apps/accounts` holds the roles, permissions, views, the `set_role` command and the audit log. The frontend side is `context/AuthProvider.tsx`, `components/auth/Guards.tsx`, `pages/auth/*` and `pages/UsersPage.tsx`.

## Roles (Django Groups `Admin` and `CI`; superusers count as Admin)

| | Admin | CI |
|---|---|---|
| Site Portfolio, Overview, 4G, LWE, Threshold Analysis, Data source & quality | ✓ | ✓ |
| Add Row, Upload CSV, Add New Site (checked in the browser; nothing is written to the server) | ✓ | ✓ |
| Read the active workbook status (`GET dashboard/workbook/`) | ✓ | ✓ |
| Upload the Master workbook (`POST dashboard/workbook/`) | ✓ | 403 |
| Team performance (`dashboard/teams/`) | ✓ | 403 |
| CSV arrival tracking: raw files (`raw-files/`, `upload/`) and email (`email/*`) | ✓ | 403 |
| CSV arrival tracking: data and upload status (`arrival-tracker/`, also limited to the user's circles) | ✓ | 403 |
| Deadlines (part of CSV arrival tracking; held in the browser) | ✓ | page refused |
| Users & roles (`auth/users/*`) | ✓ | 403 |

- **Users without a role:** a user in neither group cannot sign in.
- **Self-protection:** Admins cannot change their own role or deactivate themselves.
- **Superusers** are managed only with `manage.py`. The API refuses to modify a superuser unless the caller is one.

## Provisioning

**First Admin** (on the server; the password is typed at the prompt and never stored in the code or `.env`):

```bash
cd backend
python manage.py createsuperuser          # login ID and a strong password (validators apply)
python manage.py set_role <login_id> admin   # optional: superusers already count as Admin
```

**CI and other users:** sign in as an Admin and open **Administration → Users & roles**.

1. Enter the login ID, the name and the role, then select **Create user**.
2. A random temporary password is shown **once**. Give it to the user through a secure channel; it is never logged and cannot be shown again.
3. At first sign-in the user must set their own password.

**From the same page you can:**
- change a role;
- **Reset password**: a new temporary password, and the user is signed out everywhere;
- **Deactivate**: the user can no longer sign in, and their sessions are deleted;
- **Sign out everywhere**: deletes the user's sessions.

There is no public registration endpoint.

## Protections

- **Passwords:** Django's PBKDF2 hashing and validators (minimum 10 characters, not similar to the login ID, not common, not only digits).
- **Sign-in throttling:**
  - 5 attempts per minute per login ID (`LOGIN_RATE_PER_USER`);
  - 20 attempts per minute per address (`LOGIN_RATE_PER_IP`).

  The counts are kept in Django's cache. With several server processes, configure a shared cache such as Redis.
- **Generic sign-in error:** wrong password, unknown login ID, inactive account and no role all return the same "Invalid login ID or password."
- **No mass assignment:** account fields are explicit (login ID, names, email, role). `is_superuser`, `is_staff` and groups sent by a client are ignored. The role always comes from the server session, never from the request.
- **Audit log:**
  - It goes to `backend/logs/audit.log` (`AUDIT_LOG_FILE`) and the console, and it is git-ignored.
  - It records sign-in success and failure, sign-out, password changes, account creation, role changes, deactivation, password resets and session revocation.
  - It never records passwords, temporary passwords, session IDs or tokens. Tests do not write to it.
- **Django admin (`/admin/`):** staff only. Portal accounts are created with `is_staff=False`.

## Settings (`backend/.env`)

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | — | Required when `DEBUG` is off |
| `DEBUG` | False | Keep False in production |
| `ALLOWED_HOSTS` | localhost,127.0.0.1 | Set to the real host names |
| `CORS_ALLOWED_ORIGINS` | Vite dev origins | The frontend origin(s) |
| `CSRF_TRUSTED_ORIGINS` | = CORS origins | The frontend origin(s), with the scheme |
| `SESSION_IDLE_MINUTES` | 30 | Idle session expiry |
| `SESSION_COOKIE_SAMESITE` / `CSRF_COOKIE_SAMESITE` | Lax | `None` only for a cross-site frontend over HTTPS |
| `SECURE_SSL_REDIRECT` | True when DEBUG is off | Redirects HTTP to HTTPS |
| `SECURE_HSTS_SECONDS` | 3600 when DEBUG is off | Raise once HTTPS is confirmed |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | False | Only if every subdomain is HTTPS |
| `TRUST_X_FORWARDED_PROTO` | False | True only behind a proxy that sets the header |
| `LOGIN_RATE_PER_USER` / `LOGIN_RATE_PER_IP` | 5/min, 20/min | Sign-in throttling |
| `AUDIT_LOG_FILE` | backend/logs/audit.log | |

When `DEBUG` is off, session and CSRF cookies are `Secure`, HTTP is redirected to HTTPS and HSTS is sent. `manage.py check --deploy` then reports only the two optional HSTS settings (subdomains, preload).

## Development sign-in bypass

A **Continue without signing in** button on the sign-in page, for local testing only. It signs in as the existing account `DEV_LOGIN_USER`, with that account's own role.

**When it works:** only if all of these hold:
- the backend runs with `DEBUG=True`;
- `DEV_LOGIN_BYPASS=True` is set;
- the request comes from this computer (127.0.0.1 or ::1);
- the account exists, is active and has a role.

The request also needs the CSRF token.

**Otherwise:** `/api/auth/dev-login/` answers 404 and the button is not shown. With `DEBUG=False` the setting is ignored, so it cannot be enabled in production.

**Audit:** each use is logged as `login_bypass`.

**Turning it off:** remove `DEV_LOGIN_BYPASS` from `backend/.env`, or set it to False, before any shared or production use.

## Limitations and pending decisions

1. **No circle assignment exists**, so a CI sees every circle. Restricting data by circle needs an assignment model, which was not invented here.
2. **Server-side data is the same for every role:** CSV arrival contacts, follow-ups, deadlines and the data-entry pages hold their data in the browser only (the tracker's data and upload status are read from the database, Admins only). The pages are restricted by role, but there is no server-side operational data to protect yet.
3. **Tests run on SQLite:** the PostgreSQL role `bsnl_portal_app` cannot create the test database (`permission denied to create database`). Running them on PostgreSQL needs `CREATEDB` for a test role, or a separate test database, which is for a DBA to approve.
4. **Production deployment still needs:** HTTPS termination, real `ALLOWED_HOSTS` and origins, a `SECRET_KEY` from a secret store, a shared cache for throttling, and log rotation and retention for the audit log.

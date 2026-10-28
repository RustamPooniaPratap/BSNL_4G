"""Which circles a user may upload raw daily data for and export.

- Admin and NOC Lead: every circle (``None`` = not limited).
- CI: only the circles an Admin assigned to the account (AccountProfile.circles). A CI user without circles
  gets an empty set, i.e. no upload or export at all, never unrestricted access.
- No portal role: nothing.

Every raw-upload and export endpoint checks this on the server; the frontend only uses it to choose what to show.
"""
from __future__ import annotations

from .models import AccountProfile
from .roles import ADMIN, CI, NOC_LEAD, role_of

# Circle codes as stored in the site master (UptimeSite.circle).
KNOWN_CIRCLES = ('AP', 'BH', 'CG', 'JH', 'MH', 'MP', 'OD', 'RJ', 'TL', 'UP', 'WB')


def allowed_circles(user) -> set[str] | None:
    """None: every circle. Otherwise the set of circle codes (possibly empty)."""
    role = role_of(user)
    if role in (ADMIN, NOC_LEAD):
        return None
    if role == CI:
        profile = getattr(user, 'portal_profile', None)
        return {str(c).upper() for c in (profile.circles if profile else [])}
    return set()


def may_use_circle(user, circle: str) -> bool:
    allowed = allowed_circles(user)
    return allowed is None or circle.upper() in allowed


def assigned_circles(user) -> list[str]:
    profile = getattr(user, 'portal_profile', None)
    return sorted({str(c).upper() for c in (profile.circles if profile else [])})


def set_circles(user, circles: list[str]) -> None:
    AccountProfile.objects.update_or_create(user=user, defaults={'circles': sorted({c.upper() for c in circles})})
    user.__dict__.pop('portal_profile', None)  # drop the cached profile so the next read sees the change

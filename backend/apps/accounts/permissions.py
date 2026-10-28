"""Reusable DRF permissions. The project default is IsPortalUser, so every endpoint is
closed unless a view opts out explicitly (only health and the login flow do)."""
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import APIException
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import must_change_password
from .roles import ADMIN, role_of


class SessionAuth(SessionAuthentication):
    """Django session authentication (CSRF enforced for signed-in users); answers 401 when signed out."""

    def authenticate_header(self, request) -> str:
        return 'Session'


class PasswordChangeRequired(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = 'Change your temporary password before using the portal.'
    default_code = 'password_change_required'
    error_code = 'password_change_required'


class IsPortalUser(BasePermission):
    """Signed in, active, with a portal role, and not waiting to replace a temporary password."""
    message = 'You do not have access to this resource.'

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False  # DRF turns this into 401 for unauthenticated requests
        if must_change_password(user):
            raise PasswordChangeRequired()
        return role_of(user) is not None


class IsAdminRole(IsPortalUser):
    """Portal Admins only."""

    def has_permission(self, request, view) -> bool:
        return super().has_permission(request, view) and role_of(request.user) == ADMIN


class AdminForWrites(IsPortalUser):
    """Any portal user may read; only Admins may change (e.g. upload the Master workbook)."""

    def has_permission(self, request, view) -> bool:
        if not super().has_permission(request, view):
            return False
        return request.method in SAFE_METHODS or role_of(request.user) == ADMIN


class IsSignedIn(BasePermission):
    """Signed in and active, even with a temporary password (for "me", logout and password change)."""

    def has_permission(self, request, view) -> bool:
        return bool(request.user and request.user.is_authenticated and request.user.is_active)

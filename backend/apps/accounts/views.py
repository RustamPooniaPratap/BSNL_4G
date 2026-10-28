"""Sign-in, password change and Admin-only user management (no public registration).

Session authentication: Django's login() renews the session key and logout() flushes it
on the server. Unsafe requests need the CSRF token from ``csrf/`` (sent back in the
X-CSRFToken header); the login view enforces CSRF even though the caller is anonymous.
"""
import secrets
import string

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import audit
from .models import must_change_password, set_must_change_password
from .permissions import IsAdminRole, IsSignedIn
from .roles import ADMIN, CI, NOC_LEAD, ROLES, role_of, set_role
from .throttles import LoginIPThrottle, LoginUserThrottle

User = get_user_model()
GENERIC_LOGIN_ERROR = 'Invalid login ID or password.'


def me_payload(user) -> dict:
    return {
        'username': user.get_username(),
        'name': user.get_full_name(),
        'role': role_of(user),
        'role_label': ROLES.get(role_of(user) or '', 'No role'),
        'must_change_password': must_change_password(user),
    }


def temporary_password(length: int = 14) -> str:
    """A random temporary password that satisfies the configured validators."""
    alphabet = string.ascii_letters + string.digits
    while True:
        candidate = ''.join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate):
            try:
                validate_password(candidate)
                return candidate
            except DjangoValidationError:
                continue


def revoke_sessions(user) -> int:
    """Delete every server-side session that belongs to the user."""
    revoked = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if str(session.get_decoded().get('_auth_user_id')) == str(user.pk):
            session.delete()
            revoked += 1
    return revoked


# --- Sign-in ----------------------------------------------------------------------------------

@method_decorator(ensure_csrf_cookie, name='dispatch')
class CsrfView(APIView):
    """Sets the CSRF cookie and returns the token for the X-CSRFToken header (kept in memory by the app)."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({'csrf_token': get_token(request)})


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, trim_whitespace=True)
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    # "Remember me": keep the session for REMEMBER_ME_DAYS (renewed on use) and across browser restarts.
    remember = serializers.BooleanField(required=False, default=False)


@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginIPThrottle, LoginUserThrottle]

    def post(self, request):
        data = LoginSerializer(data=request.data)
        if not data.is_valid():
            return Response({'error': GENERIC_LOGIN_ERROR, 'details': {}}, status=status.HTTP_400_BAD_REQUEST)
        username = data.validated_data['username']
        # authenticate() refuses inactive users (ModelBackend), with the same generic error.
        user = authenticate(request, username=username, password=data.validated_data['password'])
        if user is None or role_of(user) is None:
            audit('login_failed', request, login_id=username)
            return Response({'error': GENERIC_LOGIN_ERROR, 'details': {}}, status=status.HTTP_400_BAD_REQUEST)
        login(request, user)  # new session key; any previous session data is not carried over
        remember = data.validated_data['remember']
        if remember:
            request.session.set_expiry(settings.REMEMBER_ME_DAYS * 24 * 60 * 60)
        audit('login_success', request, login_id=username, user_id=user.pk, remember=remember)
        return Response({'user': me_payload(user), 'csrf_token': get_token(request)})


LOCAL_ADDRESSES = {'127.0.0.1', '::1'}


def dev_login_user(request):
    """The account the development bypass signs in as, or None when the bypass is not allowed here."""
    if not (settings.DEBUG and settings.DEV_LOGIN_BYPASS and settings.DEV_LOGIN_USER):
        return None
    if request.META.get('REMOTE_ADDR') not in LOCAL_ADDRESSES:
        return None
    user = User.objects.filter(username=settings.DEV_LOGIN_USER, is_active=True).first()
    return user if user is not None and role_of(user) is not None else None


@method_decorator(csrf_protect, name='dispatch')
class DevLoginView(APIView):
    """Development only: sign in without a password as DEV_LOGIN_USER. 404 unless DEBUG, DEV_LOGIN_BYPASS and a local request."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        user = dev_login_user(request)
        if user is None:
            raise NotFound()
        return Response({'enabled': True, 'username': user.get_username(), 'role': role_of(user)})

    def post(self, request):
        user = dev_login_user(request)
        if user is None:
            raise NotFound()
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        audit('login_bypass', request, login_id=user.get_username(), user_id=user.pk)
        return Response({'user': me_payload(user), 'csrf_token': get_token(request)})


class LogoutView(APIView):
    permission_classes = [IsSignedIn]

    def post(self, request):
        audit('logout', request, user_id=request.user.pk)
        logout(request)  # flushes the server-side session
        return Response({'status': 'signed_out'})


class MeView(APIView):
    permission_classes = [IsSignedIn]

    def get(self, request):
        return Response({'user': me_payload(request.user)})


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)


class ChangePasswordView(APIView):
    permission_classes = [IsSignedIn]

    def post(self, request):
        data = ChangePasswordSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(data.validated_data['current_password']):
            audit('password_change_failed', request, user_id=user.pk)
            return Response({'error': 'Invalid request parameters.', 'details': {'current_password': ['The current password is not correct.']}},
                            status=status.HTTP_400_BAD_REQUEST)
        new = data.validated_data['new_password']
        if new == data.validated_data['current_password']:
            return Response({'error': 'Invalid request parameters.', 'details': {'new_password': ['Choose a password different from the current one.']}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            validate_password(new, user)
        except DjangoValidationError as exc:
            return Response({'error': 'Invalid request parameters.', 'details': {'new_password': list(exc.messages)}}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            user.set_password(new)
            user.save(update_fields=['password'])
            set_must_change_password(user, False)
        update_session_auth_hash(request, user)  # keep this session; other sessions are logged out
        request.session.cycle_key()
        audit('password_changed', request, user_id=user.pk)
        return Response({'user': me_payload(user), 'csrf_token': get_token(request)})


# --- User management (Admin only) -------------------------------------------------------------

def user_payload(user) -> dict:
    return {
        'id': user.pk,
        'username': user.get_username(),
        'name': user.get_full_name(),
        'email': user.email,
        'role': ADMIN if user.is_superuser else _group_role(user),
        'is_active': user.is_active,
        'is_superuser': user.is_superuser,
        'must_change_password': must_change_password(user),
        'last_login': user.last_login.isoformat(timespec='seconds') if user.last_login else None,
        'date_joined': user.date_joined.isoformat(timespec='seconds'),
    }


def _group_role(user) -> str | None:
    names = {g.name for g in user.groups.all()}
    return next((role for role in (ADMIN, NOC_LEAD, CI) if ROLES[role] in names), None)


class CreateUserSerializer(serializers.Serializer):
    # Explicit fields only: nothing else (is_superuser, is_staff, groups...) can be set.
    username = serializers.RegexField(r'^[\w.@+-]{3,150}$', max_length=150,
                                      error_messages={'invalid': 'Use 3 to 150 letters, digits and . @ + - _ only.'})
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    email = serializers.EmailField(required=False, allow_blank=True, default='')
    role = serializers.ChoiceField(choices=list(ROLES))

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('This login ID is already in use.')
        return value


class UpdateUserSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=list(ROLES), required=False)
    is_active = serializers.BooleanField(required=False)


class UsersView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        users = User.objects.prefetch_related('groups').select_related('portal_profile').order_by('username')
        return Response({'users': [user_payload(u) for u in users]})

    def post(self, request):
        data = CreateUserSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        password = temporary_password()
        with transaction.atomic():
            user = User(username=v['username'], first_name=v['first_name'], last_name=v['last_name'], email=v['email'],
                        is_staff=False, is_superuser=False, is_active=True)
            user.set_password(password)
            user.save()
            set_role(user, v['role'])
            set_must_change_password(user, True)
        audit('user_created', request, user_id=user.pk, login_id=user.username, role=v['role'])
        # The temporary password is returned once, to the Admin who created it; it is never logged or stored in clear.
        return Response({'user': user_payload(user), 'temporary_password': password}, status=status.HTTP_201_CREATED)


def _target(request, user_id: int):
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        raise NotFound('No such user.')
    if user.is_superuser and not request.user.is_superuser:
        raise PermissionDenied('Superuser accounts are managed with manage.py by a superuser.')
    return user


class UserDetailView(APIView):
    permission_classes = [IsAdminRole]

    def patch(self, request, user_id: int):
        user = _target(request, user_id)
        data = UpdateUserSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if user.pk == request.user.pk and (('role' in v and v['role'] != role_of(user)) or v.get('is_active') is False):
            raise PermissionDenied('You cannot change your own role or deactivate your own account.')
        if 'role' in v and v['role'] != _group_role(user):
            set_role(user, v['role'])
            audit('role_changed', request, user_id=user.pk, login_id=user.username, role=v['role'])
        if 'is_active' in v and v['is_active'] != user.is_active:
            user.is_active = v['is_active']
            user.save(update_fields=['is_active'])
            revoked = revoke_sessions(user) if not user.is_active else 0
            audit('user_activated' if user.is_active else 'user_deactivated', request, user_id=user.pk, login_id=user.username,
                  sessions_revoked=revoked)
        return Response({'user': user_payload(user)})


class ResetPasswordView(APIView):
    permission_classes = [IsAdminRole]

    def post(self, request, user_id: int):
        user = _target(request, user_id)
        if user.pk == request.user.pk:
            raise PermissionDenied('Use Change password for your own account.')
        password = temporary_password()
        with transaction.atomic():
            user.set_password(password)
            user.save(update_fields=['password'])
            set_must_change_password(user, True)
        revoked = revoke_sessions(user)
        audit('password_reset', request, user_id=user.pk, login_id=user.username, sessions_revoked=revoked)
        return Response({'user': user_payload(user), 'temporary_password': password})


class RevokeSessionsView(APIView):
    permission_classes = [IsAdminRole]

    def post(self, request, user_id: int):
        user = _target(request, user_id)
        revoked = revoke_sessions(user)
        audit('sessions_revoked', request, user_id=user.pk, login_id=user.username, sessions_revoked=revoked)
        return Response({'sessions_revoked': revoked})

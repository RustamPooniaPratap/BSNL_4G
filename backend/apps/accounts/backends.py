from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class EmailBackend(ModelBackend):
    """
    Authenticate users using their registered email ID (case-insensitive).
    Falls back to username for backward compatibility and administrative convenience.
    Only active users can authenticate (enforced by user_can_authenticate).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = kwargs.get('email') or username
        if not identifier or not password:
            return None

        identifier = str(identifier).strip()
        # Look up by email first (case-insensitive, non-empty)
        user = User.objects.filter(email__iexact=identifier).exclude(email='').first()
        if user is None:
            # Fallback to username (case-insensitive) for backward compatibility
            user = User.objects.filter(username__iexact=identifier).first()

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None


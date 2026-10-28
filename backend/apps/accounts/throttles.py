"""Login throttling: per client address and per login ID (rates in settings)."""
from rest_framework.throttling import SimpleRateThrottle


class LoginIPThrottle(SimpleRateThrottle):
    scope = 'login_ip'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class LoginUserThrottle(SimpleRateThrottle):
    scope = 'login_user'

    def get_cache_key(self, request, view):
        username = request.data.get('username') if hasattr(request, 'data') else None
        if not isinstance(username, str) or not username.strip():
            return None
        return self.cache_format % {'scope': self.scope, 'ident': username.strip().lower()[:150]}

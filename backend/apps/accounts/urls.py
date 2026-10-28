from django.urls import path

from .views import (
    ChangePasswordView, CsrfView, DevLoginView, LoginView, LogoutView, MeView, ResetPasswordView, RevokeSessionsView, UserDetailView, UsersView,
)

# No registration route: accounts are provisioned by Admins (users/) or with manage.py.
urlpatterns = [
    path('csrf/', CsrfView.as_view(), name='auth-csrf'),
    path('login/', LoginView.as_view(), name='auth-login'),
    # Development only (DEBUG + DEV_LOGIN_BYPASS + local request); 404 otherwise.
    path('dev-login/', DevLoginView.as_view(), name='auth-dev-login'),
    path('logout/', LogoutView.as_view(), name='auth-logout'),
    path('me/', MeView.as_view(), name='auth-me'),
    path('password/', ChangePasswordView.as_view(), name='auth-password'),
    path('users/', UsersView.as_view(), name='auth-users'),
    path('users/<int:user_id>/', UserDetailView.as_view(), name='auth-user'),
    path('users/<int:user_id>/reset-password/', ResetPasswordView.as_view(), name='auth-user-reset-password'),
    path('users/<int:user_id>/revoke-sessions/', RevokeSessionsView.as_view(), name='auth-user-revoke-sessions'),
]

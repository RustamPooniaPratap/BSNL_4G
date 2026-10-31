from django.urls import path

from . import views

urlpatterns = [
    path('account/', views.account, name='alert-account'),
    path('account/test/', views.account_test, name='alert-account-test'),
    path('account/activate/', views.account_activate, name='alert-account-activate'),
    path('options/', views.options, name='alert-options'),
    path('files/', views.upload_file, name='alert-files'),
    path('automations/', views.automations, name='alert-automations'),
    path('automations/preview/', views.automation_preview, name='alert-preview'),
    path('automations/<int:pk>/', views.automation_detail, name='alert-automation'),
    path('automations/<int:pk>/enable/', views.automation_enable, name='alert-enable'),
    path('automations/<int:pk>/run/', views.automation_run, name='alert-run'),
    path('history/', views.history, name='alert-history'),
    path('history/<int:pk>/', views.history_detail, name='alert-history-detail'),
    path('history/<int:pk>/retry/', views.history_retry, name='alert-retry'),
    path('history/<int:pk>/resend/', views.history_resend, name='alert-resend'),
]

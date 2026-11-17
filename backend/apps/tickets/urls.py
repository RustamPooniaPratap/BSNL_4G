from django.urls import path

from . import views

urlpatterns = [
    path('template.xlsx', views.template, name='ticket-template'),
    path('options/', views.options, name='ticket-options'),
    path('dashboard/', views.dashboard, name='ticket-dashboard'),
    path('', views.records, name='ticket-records'),
    path('<int:ticket_id>/', views.record_detail, name='ticket-detail'),
    path('<int:ticket_id>/close/', views.close_ticket, name='ticket-close'),
    path('<int:ticket_id>/reopen/', views.reopen_ticket, name='ticket-reopen'),
    path('imports/preview/', views.import_preview, name='ticket-import-preview'),
    path('imports/<int:batch_id>/', views.import_detail, name='ticket-import-detail'),
    path('imports/<int:batch_id>/commit/', views.import_commit, name='ticket-import-commit'),
    path('notifications/<int:notification_id>/retry/', views.retry_notification, name='ticket-notification-retry'),
]

from django.urls import path

from . import raw_views, views

urlpatterns = [
    path('data-source/', views.data_source, name='data-source'),
    path('imports/', views.import_list, name='import-list'),
    path('imports/preview/', views.import_preview, name='import-preview'),
    path('imports/<int:batch_id>/', views.import_detail, name='import-detail'),
    path('imports/<int:batch_id>/issues.csv', views.import_issues_csv, name='import-issues'),
    path('imports/<int:batch_id>/commit/', views.import_commit, name='import-commit'),
    path('imports/<int:batch_id>/discard/', views.import_discard, name='import-discard'),
    # Raw daily CSV uploads (Data Entry -> Upload CSV).
    path('raw-uploads/', raw_views.raw_list, name='raw-uploads'),
    path('raw-uploads/options/', raw_views.raw_options, name='raw-upload-options'),
    path('raw-uploads/preview/', raw_views.raw_preview, name='raw-upload-preview'),
    path('raw-uploads/<int:batch_id>/', raw_views.raw_detail, name='raw-upload'),
    path('raw-uploads/<int:batch_id>/rows/', raw_views.raw_rows, name='raw-upload-rows'),
    path('raw-uploads/<int:batch_id>/issues.csv', raw_views.raw_issues_csv, name='raw-upload-issues'),
    path('raw-uploads/<int:batch_id>/commit/', raw_views.raw_commit, name='raw-upload-commit'),
    path('raw-uploads/<int:batch_id>/discard/', raw_views.raw_discard, name='raw-upload-discard'),
    # CSV arrival tracking: stored daily-data coverage and raw uploads per circle and date.
    path('arrival-tracker/', raw_views.arrival_tracker, name='arrival-tracker'),
]

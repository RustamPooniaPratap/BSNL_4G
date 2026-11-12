"""Raw daily CSV uploads and the CSV arrival tracker on the data layer, mounted at /api/ (config/urls.py)."""
from django.urls import path

from . import raw_views

urlpatterns = [
    path('raw-uploads/', raw_views.raw_list, name='raw-uploads'),
    path('raw-uploads/options/', raw_views.raw_options, name='raw-upload-options'),
    path('raw-uploads/preview/', raw_views.raw_preview, name='raw-upload-preview'),
    path('raw-uploads/<int:batch_id>/', raw_views.raw_detail, name='raw-upload'),
    path('raw-uploads/<int:batch_id>/rows/', raw_views.raw_rows, name='raw-upload-rows'),
    path('raw-uploads/<int:batch_id>/issues.csv', raw_views.raw_issues_csv, name='raw-upload-issues'),
    path('raw-uploads/<int:batch_id>/commit/', raw_views.raw_commit, name='raw-upload-commit'),
    path('raw-uploads/<int:batch_id>/discard/', raw_views.raw_discard, name='raw-upload-discard'),
    path('arrival-tracker/', raw_views.arrival_tracker, name='arrival-tracker'),
]

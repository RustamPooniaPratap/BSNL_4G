"""Consolidation Matrix import endpoints on the new data layer, mounted at /api/sitedata/matrix/ (config/urls.py)."""
from django.urls import path

from . import matrix_views

urlpatterns = [
    path('', matrix_views.matrix_list, name='sitedata-matrix-list'),
    path('preview/', matrix_views.matrix_preview, name='sitedata-matrix-preview'),
    path('<int:batch_id>/', matrix_views.matrix_detail, name='sitedata-matrix-detail'),
    path('<int:batch_id>/commit/', matrix_views.matrix_commit, name='sitedata-matrix-commit'),
    path('<int:batch_id>/discard/', matrix_views.matrix_discard, name='sitedata-matrix-discard'),
    path('<int:batch_id>/issues.csv', matrix_views.matrix_issues_csv, name='sitedata-matrix-issues'),
]

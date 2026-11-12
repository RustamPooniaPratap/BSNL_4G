"""Data administration of the data layer (Admins), mounted at /api/sitedata/ (config/urls.py)."""
from django.urls import path

from . import data_views

urlpatterns = [
    path('daily/correct/', data_views.daily_correct, name='sitedata-daily-correct'),
    path('daily/history/', data_views.daily_history, name='sitedata-daily-history'),
    path('lwe-mapping/', data_views.mapping_list, name='sitedata-mapping-list'),
    path('lwe-mapping/preview/', data_views.mapping_preview, name='sitedata-mapping-preview'),
    path('lwe-mapping/<int:batch_id>/', data_views.mapping_detail, name='sitedata-mapping-detail'),
    path('lwe-mapping/<int:batch_id>/commit/', data_views.mapping_commit, name='sitedata-mapping-commit'),
    path('lwe-mapping/<int:batch_id>/discard/', data_views.mapping_discard, name='sitedata-mapping-discard'),
    path('lwe-mapping/<int:batch_id>/issues.csv', data_views.mapping_issues_csv, name='sitedata-mapping-issues'),
    path('months/', data_views.months, name='sitedata-months'),
    path('months/finalize/', data_views.months_finalize, name='sitedata-months-finalize'),
    path('months/reopen/', data_views.months_reopen, name='sitedata-months-reopen'),
    path('reporting-units/', data_views.reporting_units, name='sitedata-reporting-units'),
    path('reporting-units/<int:unit_id>/', data_views.reporting_unit, name='sitedata-reporting-unit'),
    path('coverage-threshold/', data_views.coverage_threshold, name='sitedata-coverage-threshold'),
]

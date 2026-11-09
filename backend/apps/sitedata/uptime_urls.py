"""Up-Time Report import into the new data layer, mounted at /api/sitedata/uptime/ (config/urls.py)."""
from django.urls import path

from . import uptime_views

urlpatterns = [
    path('', uptime_views.uptime_list, name='sitedata-uptime-list'),
    path('preview/', uptime_views.uptime_preview, name='sitedata-uptime-preview'),
    path('unmatched/', uptime_views.unmatched_report, name='sitedata-unmatched'),
    path('unmatched/refresh/', uptime_views.unmatched_refresh, name='sitedata-unmatched-refresh'),
    path('unmatched/map/', uptime_views.unmatched_map, name='sitedata-unmatched-map'),
    path('unmatched/process/', uptime_views.unmatched_process, name='sitedata-unmatched-process'),
    path('<int:batch_id>/', uptime_views.uptime_detail, name='sitedata-uptime-detail'),
    path('<int:batch_id>/commit/', uptime_views.uptime_commit, name='sitedata-uptime-commit'),
    path('<int:batch_id>/discard/', uptime_views.uptime_discard, name='sitedata-uptime-discard'),
    path('<int:batch_id>/issues.csv', uptime_views.uptime_issues_csv, name='sitedata-uptime-issues'),
]

"""Root URL configuration. Every operational data endpoint is served by the data layer (apps.sitedata)."""
from django.urls import include, path

urlpatterns = [
    path('api/auth/', include('apps.accounts.urls')),
    path('api/', include('apps.common.urls')),
    path('api/dashboard/', include('apps.dashboard.urls')),
    path('api/', include('apps.sitedata.raw_urls')),  # raw daily CSV uploads and the CSV arrival tracker
    path('api/rca/', include('apps.rca.urls')),
    path('api/organization/', include('apps.organization.urls')),
    path('api/master-data/', include('apps.masterdata.urls')),
    path('api/alerts/', include('apps.alerts.urls')),
    path('api/tickets/', include('apps.tickets.urls')),
    path('api/bsnl/', include('apps.bsnl.urls')),  # BSNL Module: Auto Email Reports and BSNL Letters (apps/bsnl)
    path('api/all-kpis/', include('apps.allkpis.urls')),  # All KPI's module (apps/allkpis/README.md)
    path('api/site-portfolio/', include('apps.sitedata.urls')),  # Site Portfolio (apps/sitedata/portfolio.py)
    path('api/sitedata/matrix/', include('apps.sitedata.matrix_urls')),  # Consolidation Matrix import (apps/sitedata/matrix.py)
    path('api/sitedata/uptime/', include('apps.sitedata.uptime_urls')),  # Up-Time Report import (apps/sitedata/uptime_master.py)
    path('api/sitedata/', include('apps.sitedata.data_urls')),  # corrections, LWE Band ID mapping, monthly finalization
    path('api/api-master/', include('apps.api_master.urls')),  # API Master administration (apps/api_master), Admins only
]

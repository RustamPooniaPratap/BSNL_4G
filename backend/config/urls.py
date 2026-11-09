"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, include

urlpatterns = [
    path('api/auth/', include('apps.accounts.urls')),
    path('api/', include('apps.common.urls')),
    path('api/dashboard/', include('apps.dashboard.urls')),
    path('api/', include('apps.uptimedb.urls')),
    path('api/rca/', include('apps.rca.urls')),
    path('api/organization/', include('apps.organization.urls')),
    path('api/master-data/', include('apps.masterdata.urls')),
    path('api/alerts/', include('apps.alerts.urls')),
    path('api/all-kpis/', include('apps.allkpis.urls')),  # optional All KPI's module (apps/allkpis/README.md)
    path('api/site-portfolio/', include('apps.sitedata.urls')),
    path('api/sitedata/matrix/', include('apps.sitedata.matrix_urls')),
    path('api/sitedata/uptime/', include('apps.sitedata.uptime_urls')),  # Up-Time Report into the new data layer (apps/sitedata/uptime_master.py)  # Consolidation Matrix import (apps/sitedata/matrix.py)  # Site Portfolio on the new data layer (apps/sitedata/portfolio.py)
]

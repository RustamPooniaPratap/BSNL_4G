from django.urls import path

from . import views

# Mounted at /api/all-kpis/ by one line in config/urls.py (remove both to remove the module).
urlpatterns = [
    path('filters/', views.filters, name='allkpis-filters'),
    path('summary/', views.summary, name='allkpis-summary'),
    path('trends/', views.trends, name='allkpis-trends'),
    path('hierarchy/', views.hierarchy, name='allkpis-hierarchy'),
    path('sites/', views.sites, name='allkpis-sites'),
    path('rca/', views.rca, name='allkpis-rca'),
]

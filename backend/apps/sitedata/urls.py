"""Site Portfolio endpoints on the new data layer, mounted at /api/site-portfolio/ (config/urls.py)."""
from django.urls import path

from . import portfolio_views

urlpatterns = [
    path('filters/', portfolio_views.filters_view, name='site-portfolio-filters'),
    path('summary/', portfolio_views.summary_view, name='site-portfolio-summary'),
    path('breakdowns/', portfolio_views.breakdowns_view, name='site-portfolio-breakdowns'),
    path('period/', portfolio_views.period_view, name='site-portfolio-period'),
    path('conversion-activity/', portfolio_views.conversion_activity_view, name='site-portfolio-conversion-activity'),
]

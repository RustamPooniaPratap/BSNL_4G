from django.urls import path

from . import views

urlpatterns = [
    path('overview/', views.overview, name='api-master-overview'),
    path('endpoints/', views.endpoints, name='api-master-endpoints'),
    path('endpoints/sync/', views.sync, name='api-master-sync'),
    path('endpoints/<int:pk>/', views.endpoint_detail, name='api-master-endpoint'),
    path('endpoints/<int:pk>/review/', views.endpoint_review, name='api-master-endpoint-review'),
]

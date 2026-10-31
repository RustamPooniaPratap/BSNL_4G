from django.urls import path

from . import views

urlpatterns = [
    path('datasets/', views.datasets, name='master-datasets'),
    path('<str:key>/records/', views.records, name='master-records'),
    path('<str:key>/options/', views.options, name='master-options'),
    path('<str:key>/export/', views.export, name='master-export'),
]

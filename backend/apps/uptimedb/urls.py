from django.urls import path

from . import views

urlpatterns = [
    path('data-source/', views.data_source, name='data-source'),
    path('imports/', views.import_list, name='import-list'),
    path('imports/preview/', views.import_preview, name='import-preview'),
    path('imports/<int:batch_id>/', views.import_detail, name='import-detail'),
    path('imports/<int:batch_id>/issues.csv', views.import_issues_csv, name='import-issues'),
    path('imports/<int:batch_id>/commit/', views.import_commit, name='import-commit'),
    path('imports/<int:batch_id>/discard/', views.import_discard, name='import-discard'),
]

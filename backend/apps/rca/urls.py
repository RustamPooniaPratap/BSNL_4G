from django.urls import path

from . import views

urlpatterns = [
    path('options/', views.options, name='rca-options'),
    path('records/', views.records, name='rca-records'),
    path('records/<int:record_id>/', views.record_detail, name='rca-record'),
    path('records/<int:record_id>/workflow/', views.record_workflow, name='rca-workflow'),
    path('records/<int:record_id>/comments/', views.record_comments, name='rca-comments'),
    path('summary/', views.summary, name='rca-summary'),
    path('imports/', views.import_list, name='rca-imports'),
    path('imports/preview/', views.import_preview, name='rca-import-preview'),
    path('imports/<int:batch_id>/', views.import_detail, name='rca-import'),
    path('imports/<int:batch_id>/issues.csv', views.import_issues_csv, name='rca-import-issues'),
    path('imports/<int:batch_id>/commit/', views.import_commit, name='rca-import-commit'),
    path('imports/<int:batch_id>/discard/', views.import_discard, name='rca-import-discard'),
    path('causes/', views.causes, name='rca-causes'),
    path('causes/categories/', views.cause_categories, name='rca-categories'),
    path('causes/mappings/', views.cause_mappings, name='rca-mappings'),
]

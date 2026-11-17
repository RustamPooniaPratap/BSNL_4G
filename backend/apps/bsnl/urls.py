from django.urls import path

from . import views

urlpatterns = [
    path('reports/options/', views.report_options, name='bsnl-report-options'),
    path('reports/overview/', views.report_overview, name='bsnl-report-overview'),
    path('reports/preview/', views.report_preview, name='bsnl-report-preview'),
    path('reports/download/', views.report_download, name='bsnl-report-download'),
    path('reports/download-all/', views.report_download_all, name='bsnl-report-download-all'),
    path('reports/send/', views.report_send, name='bsnl-report-send'),
    path('reports/runs/', views.report_runs, name='bsnl-report-runs'),
    path('reports/schedule/', views.report_schedule, name='bsnl-report-schedule'),
    path('recipients/', views.recipients_list, name='bsnl-recipients'),
    path('recipients/<int:recipient_id>/', views.recipient_detail, name='bsnl-recipient-detail'),
    path('letters/options/', views.letter_options, name='bsnl-letter-options'),
    path('letters/overview/', views.letter_overview, name='bsnl-letter-overview'),
    path('letters/open/', views.letter_open, name='bsnl-letter-open'),
    path('letters/register.xlsx', views.letter_register_xlsx, name='bsnl-letter-register'),
    path('letters/profiles/', views.profiles, name='bsnl-letter-profiles'),
    path('letters/profiles/<str:circle_code>/', views.profile_detail, name='bsnl-letter-profile-detail'),
    path('letters/bucket-mapping/', views.bucket_mapping, name='bsnl-bucket-mapping'),
    path('letters/<int:letter_id>/', views.letter_detail, name='bsnl-letter-detail'),
    path('letters/<int:letter_id>/content/', views.letter_content, name='bsnl-letter-content'),
    path('letters/<int:letter_id>/regenerate/', views.letter_regenerate, name='bsnl-letter-regenerate'),
    path('letters/<int:letter_id>/approve/', views.letter_approve, name='bsnl-letter-approve'),
    path('letters/<int:letter_id>/status/', views.letter_status, name='bsnl-letter-status'),
    path('letters/<int:letter_id>/send/', views.letter_send, name='bsnl-letter-send'),
    path('letters/<int:letter_id>/download/<str:fmt>/', views.letter_download, name='bsnl-letter-download'),
]

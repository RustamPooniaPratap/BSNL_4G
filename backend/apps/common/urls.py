from django.urls import path
from .views import (
    email_status, health_check, list_raw_files, reminder_template, send_personal_email, send_reminder, upload_file,
)

urlpatterns = [
    path('health/', health_check, name='health-check'),
    path('upload/', upload_file, name='upload-file'),
    path('raw-files/', list_raw_files, name='list-raw-files'),
    path('email/status/', email_status, name='email-status'),
    path('email/reminder-template/', reminder_template, name='email-reminder-template'),
    path('email/reminder/', send_reminder, name='email-send-reminder'),
    path('email/send/', send_personal_email, name='email-send'),
]

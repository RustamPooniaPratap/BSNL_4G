from django.apps import AppConfig


class SitedataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.sitedata'
    label = 'sitedata'
    verbose_name = 'Site master and performance (new data layer)'

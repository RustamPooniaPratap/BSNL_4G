from django.apps import AppConfig


class UptimeDbConfig(AppConfig):
    """Migration history only (see models.py): the legacy tables are removed by migration 0007."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.uptimedb'
    verbose_name = 'Uptime database (retired)'

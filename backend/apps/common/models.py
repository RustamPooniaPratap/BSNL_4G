from django.conf import settings
from django.db import models


class Setting(models.Model):
    """Application setting stored in the database (key / JSON value), e.g. the alert worker's heartbeat. Not
    operational site data."""

    key = models.CharField(max_length=80, unique=True)
    value = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return self.key

    @classmethod
    def get(cls, key: str, default=None):
        row = cls.objects.filter(key=key).values_list('value', flat=True).first()
        return default if row is None else row

    @classmethod
    def put(cls, key: str, value, user=None) -> 'Setting':
        obj, _ = cls.objects.update_or_create(key=key, defaults={'value': value, 'updated_by': user})
        return obj

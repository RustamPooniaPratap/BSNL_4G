# Generated for the Site Master inline-editing feature.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sitedata', '0004_historical_monthly_import'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteManualOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('field', models.CharField(max_length=50)),
                ('matrix_value', models.JSONField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('site', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='manual_overrides', to='sitedata.site')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(fields=('site', 'field'), name='sitedata_site_manual_override_unique'),
                ],
            },
        ),
    ]

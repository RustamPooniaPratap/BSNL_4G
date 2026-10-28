import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from apps.dashboard import metrics, workbook

from .auth_helpers import SignedInTestCase
from .workbook_factory import write_workbook


class AlertsTests(SignedInTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        path = write_workbook(Path(cls._tmp.name) / 'master.xlsx')
        cls._override = override_settings(MASTER_WORKBOOK_PATH=str(path))
        cls._override.enable()
        workbook.clear_cache()
        cls.ds = workbook.get_dataset()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        workbook.clear_cache()
        cls._tmp.cleanup()
        super().tearDownClass()

    def ids(self, today=date(2026, 10, 4)):
        return [a['id'] for a in metrics.alerts(self.ds, today)]

    def test_alerts_are_ranked_critical_warning_info(self):
        alerts = metrics.alerts(self.ds, date(2026, 10, 10))
        self.assertEqual([a['id'] for a in alerts], [
            'sites_down_full_day', 'stale_data', 'sites_not_reported', 'data_partial_dates', 'lowest_circle',
        ])
        down = alerts[0]
        self.assertEqual(down['severity'], 'critical')
        self.assertEqual(down['title'], '1 On-Air sites down all day on 03 Oct')  # UVMP001: 1,440 minutes
        self.assertEqual(down['link'], '/?date=2026-10-03')
        self.assertEqual(alerts[1]['title'], 'Latest data is from 03 Oct (7 days ago)')
        self.assertEqual(alerts[2]['title'], '1 On-Air sites not reported on 03 Oct')  # LWEOD01

    def test_data_age_alert_only_when_older_than_a_day(self):
        self.assertNotIn('stale_data', self.ids(date(2026, 10, 4)))
        self.assertIn('stale_data', self.ids(date(2026, 10, 5)))

    def test_below_60_alert_uses_workbook_bucket(self):
        # No On-Air site is below 60% MTD in the fixture; with all sites in scope UVMP003 would be,
        # but alerts use the On-Air scope, so no alert is raised.
        self.assertNotIn('sites_below_60', self.ids())

    def test_lowest_circle_is_identified(self):
        lowest = next(a for a in metrics.alerts(self.ds, date(2026, 10, 4)) if a['id'] == 'lowest_circle')
        # LWEOD01: 720 outage minutes over 2 reported days = 75.00%, below MP 4G (80.83%).
        self.assertEqual(lowest['title'], 'Lowest MTD uptime: OD · LWE (75.00%)')
        self.assertEqual(lowest['link'], '/?report_type=LWE&circle=OD')

    def test_alerts_endpoint(self):
        with mock.patch('apps.dashboard.views.timezone.localdate', return_value=date(2026, 10, 4)):
            data = self.client.get(reverse('dashboard-alerts')).json()
        self.assertEqual(data['counts'], {'critical': 1, 'warning': 2, 'info': 1})
        self.assertEqual(data['alerts'][0]['id'], 'sites_down_full_day')

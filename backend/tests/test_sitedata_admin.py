"""Data administration of the data layer: authorized corrections (precedence 3), finalized months, the LWE Band ID
mapping import API, and the exact 98.5% threshold. Test database only."""
from datetime import date

import numpy as np
from django.urls import reverse

from apps.dashboard import metrics
from apps.sitedata import daily, rawcsv
from apps.sitedata.models import DailyPerformanceEvent, DailySitePerformance, MonthlySitePerformance, UploadBatch
from apps.sitedata.rules import outage_from_availability
from tests.auth_helpers import portal_user
from tests.test_sitedata import BAND, BAND_HEADER, MATRIX, SiteDataTestCase, oct_csv, write_csv, write_sheet

G4 = '4G Saturation'
OCT1 = date(2026, 10, 1)


class CorrectionApiTests(SiteDataTestCase):
    def setUp(self):
        super().setUp()
        self.load_matrix(MATRIX)
        self.load_uptime()
        self.client.force_login(self.admin)

    def correct(self, expected=200, **body):
        r = self.client.post(reverse('sitedata-daily-correct'), {'site': 'UVMP001', 'report_date': '2026-10-01', **body}, content_type='application/json')
        self.assertEqual(r.status_code, expected, r.content[:400])
        return r.json()

    def test_a_correction_wins_over_every_later_upload_and_keeps_the_trail(self):
        self.correct(availability_pct=95, reason='verified with CNMC')
        rec = DailySitePerformance.objects.get(site__site_key='UVMP001', report_date=OCT1)
        self.assertEqual((rec.availability_pct, rec.batch.kind), (95, UploadBatch.Kind.CORRECTION))
        later = self.load_uptime(name='later.xlsx')
        self.assertEqual((later.records_conflict, later.records_superseded), (1, 0))
        batch = rawcsv.preview(write_csv(self.tmp / 'd.csv', oct_csv('UVMP001', '10')), 'd.csv', technology=G4, circle='MP', reporting_date=OCT1, user=self.admin)
        self.assertEqual(rawcsv.commit(batch, user=self.admin).records_conflict, 1)
        self.assertEqual(DailySitePerformance.objects.get(pk=rec.pk).availability_pct, 95)
        history = self.client.get(reverse('sitedata-daily-history'), {'site': 'UVMP001', 'date': '2026-10-01'}).json()
        self.assertEqual(history['events'][-1]['action'], DailyPerformanceEvent.Action.CORRECTION)
        self.assertEqual(history['events'][-1]['reason'], 'verified with CNMC')

    def test_a_missing_site_day_can_be_added_and_a_reason_is_required(self):
        self.correct(400, availability_pct=90)
        r = self.client.post(reverse('sitedata-daily-correct'), {'site': 'UVMP002', 'report_date': '2026-10-20', 'availability_pct': 90, 'reason': 'site log'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(DailySitePerformance.objects.get(site__site_key='UVMP002', report_date=date(2026, 10, 20)).batch.kind, UploadBatch.Kind.CORRECTION)
        self.correct(400, availability_pct=101, reason='x')

    def test_finalized_months_refuse_uploads_and_need_an_explicit_admin_correction(self):
        r = self.client.post(reverse('sitedata-months-finalize'), {'month': '2026-10-01', 'confirm': True}, content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(MonthlySitePerformance.objects.filter(month=OCT1, finalized_at__isnull=False).exists())
        batch = rawcsv.preview(write_csv(self.tmp / 'd.csv', oct_csv('UVMP002', '50', day='10-10-2026')), 'd.csv', technology=G4, circle='MP', reporting_date=date(2026, 10, 10), user=self.admin)
        self.assertEqual(batch.records_accepted, 1)  # a new site-day in the finalized month
        with self.assertRaises(daily.FinalizedPeriod):
            rawcsv.commit(batch, user=self.admin)
        self.assertIn('finalized', self.correct(409, availability_pct=90, reason='late fix')['error'])
        self.correct(availability_pct=90, reason='approved late fix', force=True)

    def test_non_admins_cannot_correct(self):
        self.client.force_login(portal_user('corr-noc', 'noc_lead'))
        self.correct(403, availability_pct=90, reason='x')


class MappingApiTests(SiteDataTestCase):
    def test_preview_commit_and_list(self):
        self.load_matrix(MATRIX)
        self.client.force_login(self.admin)
        path = write_sheet(self.tmp / 'band.xlsx', BAND_HEADER, BAND, title='Sheet1', preamble=False)
        with open(path, 'rb') as handle:
            r = self.client.post(reverse('sitedata-mapping-preview'), {'file': handle})
        self.assertEqual(r.status_code, 201, r.content[:400])
        batch_id = r.json()['id']
        self.assertEqual(self.client.post(reverse('sitedata-mapping-commit', args=[batch_id]), {'confirm': True}, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.post(reverse('sitedata-mapping-commit', args=[batch_id]), {'confirm': True}, content_type='application/json').status_code, 409)
        self.assertEqual(UploadBatch.objects.get(pk=batch_id).uploaded_by, self.admin)
        self.assertEqual(len(self.client.get(reverse('sitedata-mapping-list')).json()['imports']), 1)


class ThresholdBoundaryTests(SiteDataTestCase):
    def test_exactly_98_5_percent_is_not_nsla_even_through_outage_minutes(self):
        outage = outage_from_availability(98.5)  # 21.60000000000002 in floating point
        self.assertGreater(outage, 21.6)
        block = np.array([[outage] * 30])
        uptime = metrics.site_uptime(block)
        self.assertEqual(list(metrics.bucket_ids(uptime)), ['gte_98_5'])
        self.assertEqual(list(metrics.bucket_ids(np.array([98.49]))), ['97_98_5'])

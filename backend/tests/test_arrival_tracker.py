"""CSV arrival tracking on the data layer (/api/arrival-tracker/, apps.sitedata.arrivals): coverage of the daily table
against the sites On-Air on each date (matrix Site On-Air Date), raw CSV upload states, and Admin-only access.
Test database only."""
from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.sitedata import arrivals
from apps.sitedata.models import UploadBatch
from tests.auth_helpers import portal_user
from tests.sitedata_factory import make_daily, make_site

G4, LWE = '4G Saturation', 'LWE'
DAY = date(2026, 10, 5)


class ArrivalTrackerTests(TestCase):
    def setUp(self):
        self.mp1 = make_site('UVMP001', technology=G4, circle='MP', on_air_date=date(2026, 1, 1))
        self.mp2 = make_site('UVMP002', technology=G4, circle='MP', on_air_date=date(2026, 10, 5))  # On-Air from 5 Oct
        self.mp3 = make_site('UVMP003', technology=G4, circle='MP', on_air_date=None)  # never On-Air: not expected
        self.lwe = make_site('LWEMP01', technology=LWE, circle='MP', on_air_date=date(2026, 1, 1))
        self.admin = portal_user('tracker-admin', 'admin')

    def item(self, data, project, circle):
        return next(i for i in data['items'] if (i['project'], i['circle']) == (project, circle))

    def test_expected_sites_follow_the_matrix_on_air_dates(self):
        make_daily(self.mp1, date(2026, 10, 4), 0)
        make_daily(self.mp1, DAY, 0)
        data = arrivals.tracker(DAY, None, date(2026, 10, 4), DAY)
        mp = self.item(data, G4, 'MP')
        self.assertEqual((mp['sites_total'], mp['sites_expected'], mp['sites_with_data'], mp['data_state']), (3, 2, 1, 'partial'))
        self.assertEqual([(r['date'], r['state']) for r in mp['range']], [('2026-10-04', 'complete'), ('2026-10-05', 'partial')])
        self.assertEqual(mp['latest_complete_date'], '2026-10-04')
        self.assertEqual(mp['data_source']['master_workbook'], 1)  # set by the Uptime Master
        # 4G data never satisfies LWE of the same circle.
        self.assertEqual(self.item(data, LWE, 'MP')['data_state'], 'none')

    def test_upload_states_of_the_date(self):
        UploadBatch.objects.create(kind=UploadBatch.Kind.RAW_CSV_4G, original_filename='mp.csv', technology=G4, circle='MP', reporting_date=DAY,
                                   processing_status='committed', committed_at=timezone.now(), records_accepted=2)
        UploadBatch.objects.create(kind=UploadBatch.Kind.RAW_CSV_LWE, original_filename='lwe.csv', technology=LWE, circle='MP', reporting_date=DAY,
                                   records_accepted=1)
        data = arrivals.tracker(DAY, None)
        self.assertEqual(self.item(data, G4, 'MP')['upload_state'], 'imported')
        self.assertEqual(self.item(data, LWE, 'MP')['upload_state'], 'awaiting_confirmation')
        self.assertEqual(self.item(data, G4, 'MP')['latest_import_date'], DAY.isoformat())

    def test_admin_only_and_parameters(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('arrival-tracker'), {'date': DAY.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(reverse('arrival-tracker')).status_code, 400)
        self.assertEqual(self.client.get(reverse('arrival-tracker'), {'date': '2026-10-05', 'start': '2026-10-01'}).status_code, 400)
        ci = portal_user('tracker-ci', 'ci')
        self.client.force_login(ci)
        self.assertEqual(self.client.get(reverse('arrival-tracker'), {'date': DAY.isoformat()}).status_code, 403)

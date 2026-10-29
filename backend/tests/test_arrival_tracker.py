"""CSV arrival tracking (/daily-ingestion): stored daily-data coverage and raw CSV uploads per project, circle and date.

Synthetic records only, in the isolated test database. Daily records written by the "Master workbook" batch stand in
for the workbook import; raw uploads go through the real preview / commit endpoints.
"""
from datetime import date

from django.urls import reverse

from apps.uptimedb import arrivals
from apps.uptimedb.models import DataImportBatch, SiteDailyPerformance, UptimeSite
from tests.auth_helpers import portal_user
from tests.test_raw_upload import RawUploadTestCase, row

OD_4G = ('UVOR001', 'UVOR002', 'UVOR003')


class ArrivalTrackerTestCase(RawUploadTestCase):
    def setUp(self):
        super().setUp()
        # Not On-Air: in the master, but never an expected daily record.
        self.off_air = UptimeSite.objects.create(project='4G Saturation', circle='OD', site_id='UVOR009', site_key='UVOR009',
                                                 batch=self.master, source_row=9, on_air=False)
        self.client.force_login(self.admin)

    def store(self, sites, day, outage=10.0, batch=None):
        for site in sites:
            target = self.off_air if site == 'UVOR009' else self.sites[site]
            SiteDailyPerformance.objects.create(site=target, date=day, outage_minutes=outage, batch=batch or self.master)

    def get(self, day, **params):
        response = self.client.get(reverse('arrival-tracker'), {'date': day, **params})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def item(self, body, circle='OD', project='4G Saturation'):
        return next(i for i in body['items'] if i['project'] == project and i['circle'] == circle)


class CoverageTests(ArrivalTrackerTestCase):
    def test_master_workbook_data_is_recognised_without_any_raw_upload(self):
        self.store(OD_4G, date(2026, 10, 12))
        od = self.item(self.get('2026-10-12'))
        self.assertEqual((od['data_state'], od['upload_state'], od['uploads']), ('complete', 'none', []))  # not "pending"
        self.assertEqual((od['sites_expected'], od['sites_with_data'], od['sites_missing'], od['coverage_pct']), (3, 3, 0, 100.0))
        self.assertEqual(od['data_source'], {'master_workbook': 3, 'raw_daily_csv': 0})
        self.assertEqual(od['sites_total'], 4)  # the off-air site is in the master but not expected

    def test_partial_coverage_is_not_complete(self):
        self.store(OD_4G[:2], date(2026, 10, 12))
        self.store(['UVOR009'], date(2026, 10, 12))  # an off-air site's record never fills an expected one
        od = self.item(self.get('2026-10-12'))
        self.assertEqual((od['data_state'], od['sites_with_data'], od['sites_missing'], od['coverage_pct']), ('partial', 2, 1, 66.67))
        self.assertEqual(od['records_observed'], 3)

    def test_no_usable_data_stays_no_data_and_invalid_values_are_never_usable(self):
        day = date(2026, 10, 12)
        self.store(['UVOR001'], day, outage=None)    # not reported
        self.store(['UVOR002'], day, outage=-5)      # outside 0..1440
        self.store(['UVOR003'], day, outage=1500)
        od = self.item(self.get('2026-10-12'))
        self.assertEqual((od['data_state'], od['sites_with_data'], od['sites_invalid'], od['sites_missing']), ('none', 0, 2, 1))
        self.assertIsNone(od['latest_data_date'])
        mp = self.item(self.get('2026-10-12'), circle='MP')
        self.assertEqual((mp['data_state'], mp['upload_state'], mp['coverage_pct']), ('none', 'none', 0.0))

    def test_latest_dates_come_from_stored_reporting_dates_not_upload_times(self):
        self.store(OD_4G, date(2026, 10, 5))
        self.store(OD_4G[:1], date(2026, 10, 9))  # later but partial
        DataImportBatch.objects.create(kind='raw_daily_csv', project='4G Saturation', circle='OD', reporting_date=date(2026, 10, 2),
                                       original_filename='old.csv', checksum_sha256='y', sheet_name='', stored_path='-',
                                       status=DataImportBatch.Status.REJECTED)  # uploaded now, for an older date
        od = self.item(self.get('2026-10-01'))
        self.assertEqual((od['latest_data_date'], od['latest_complete_date'], od['latest_upload_date'], od['latest_import_date']),
                         ('2026-10-09', '2026-10-05', '2026-10-02', None))
        self.assertEqual(od['data_state'], 'none')  # data on other dates says nothing about the selected one

    def test_the_same_rules_apply_to_lwe(self):
        SiteDailyPerformance.objects.create(site=self.sites['LWEOD0001'], date=date(2026, 10, 12), outage_minutes=0, batch=self.master)
        body = self.get('2026-10-12')
        lwe = self.item(body, project='LWE')
        self.assertEqual((lwe['data_state'], lwe['sites_with_data'], lwe['sites_expected'], lwe['upload_state']), ('complete', 1, 1, 'none'))
        self.assertEqual(self.item(self.get('2026-10-13'), project='LWE')['data_state'], 'none')
        self.assertEqual([(i['project'], i['circle']) for i in body['items']], [('4G Saturation', 'MP'), ('4G Saturation', 'OD'), ('LWE', 'OD')])

    def test_each_date_returns_its_own_results(self):
        self.store(OD_4G, date(2026, 10, 12))
        self.store(OD_4G[:1], date(2026, 10, 13))
        first, second, third = self.get('2026-10-12'), self.get('2026-10-13'), self.get('2026-10-14')
        self.assertEqual([b['reporting_date'] for b in (first, second, third)], ['2026-10-12', '2026-10-13', '2026-10-14'])
        self.assertEqual([self.item(b)['data_state'] for b in (first, second, third)], ['complete', 'partial', 'none'])

    def test_the_daily_range_shows_gaps(self):
        self.store(OD_4G, date(2026, 10, 10))
        self.store(OD_4G[:2], date(2026, 10, 12))
        od = self.item(self.get('2026-10-12', start='2026-10-10', end='2026-10-13'))
        self.assertEqual([(r['date'], r['state'], r['sites_with_data']) for r in od['range']],
                         [('2026-10-10', 'complete', 3), ('2026-10-11', 'none', 0), ('2026-10-12', 'partial', 2), ('2026-10-13', 'none', 0)])
        default = self.get('2026-10-12')['range']
        self.assertEqual((default['start'], default['end']), ('2026-09-29', '2026-10-12'))

    def test_bad_dates_and_ranges_are_refused(self):
        url = reverse('arrival-tracker')
        for params in ({}, {'date': 'yesterday'}, {'date': '2026-10-12', 'start': '2026-10-12'},
                       {'date': '2026-10-12', 'start': '2026-10-13', 'end': '2026-10-12'},
                       {'date': '2026-10-12', 'start': '2026-01-01', 'end': '2026-10-12'}):
            self.assertEqual(self.client.get(url, params).status_code, 400, params)

    def test_reading_the_tracker_changes_nothing(self):
        self.store(OD_4G, date(2026, 10, 12))
        before = (SiteDailyPerformance.objects.count(), DataImportBatch.objects.count(), UptimeSite.objects.count())
        self.get('2026-10-12', start='2026-10-01', end='2026-10-12')
        self.assertEqual((SiteDailyPerformance.objects.count(), DataImportBatch.objects.count(), UptimeSite.objects.count()), before)


class UploadStatusTests(ArrivalTrackerTestCase):
    def upload_as(self, user, rows, **kwargs):
        self.client.force_login(user)
        body = self.upload(rows, **kwargs).json()
        self.client.force_login(self.admin)
        return body

    def test_a_validated_upload_is_received_but_not_imported(self):
        preview = self.upload_as(self.ci_od, [row('UVOR001', '99'), row('UVOR002', '98')])
        od = self.item(self.get('2026-10-13'))
        self.assertEqual((od['data_state'], od['upload_state']), ('none', 'awaiting_confirmation'))
        upload = od['uploads'][0]
        self.assertEqual((upload['id'], upload['file'], upload['uploaded_by'], upload['ready_to_import'], upload['imported']),
                         (preview['id'], 'nw_aval_day.csv', 'raw-ci-od', 2, None))

    def test_an_import_updates_both_indicators_independently(self):
        preview = self.upload_as(self.ci_od, [row('UVOR001', '99'), row('UVOR002', '98')])
        self.client.force_login(self.ci_od)
        self.assertEqual(self.commit(preview['id']).status_code, 200)
        self.client.force_login(self.admin)
        od = self.item(self.get('2026-10-13'))
        self.assertEqual((od['data_state'], od['upload_state'], od['sites_with_data']), ('partial', 'imported', 2))  # UVOR003 not in the file
        self.assertEqual(od['data_source'], {'master_workbook': 0, 'raw_daily_csv': 2})
        self.assertEqual((od['uploads'][0]['imported'], od['latest_import_date'], od['latest_upload_date']), (2, '2026-10-13', '2026-10-13'))

    def test_blocked_and_discarded_uploads_stay_visible(self):
        self.upload_as(self.ci_od, [row('UVOR001', '99', day='12-10-2026')])  # the file's date is not the entered date
        od = self.item(self.get('2026-10-13'))
        self.assertEqual((od['upload_state'], od['uploads'][0]['state']), ('blocked', 'blocked'))
        self.assertTrue(od['uploads'][0]['error'])
        preview = self.upload_as(self.ci_od, [row('UVOR001', '99')])
        self.client.force_login(self.ci_od)
        self.client.post(reverse('raw-upload-discard', args=[preview['id']]))
        self.client.force_login(self.admin)
        od = self.item(self.get('2026-10-13'))
        self.assertEqual(sorted(u['state'] for u in od['uploads']), ['blocked', 'discarded'])
        self.assertEqual(od['upload_state'], 'blocked')

    def test_complete_master_data_with_a_file_that_adds_nothing(self):
        self.store(OD_4G, date(2026, 10, 13), outage=0)  # 100% availability, as the file below says
        self.upload_as(self.ci_od, [row('UVOR001', '100'), row('UVOR002', '100'), row('UVOR003', '100')])
        od = self.item(self.get('2026-10-13'))
        self.assertEqual((od['data_state'], od['upload_state'], od['data_source']['master_workbook']), ('complete', 'nothing_to_import', 3))


class PermissionTests(ArrivalTrackerTestCase):
    def test_only_admins_use_the_tracker(self):
        url = reverse('arrival-tracker')
        for user in (self.noc, self.ci_od, portal_user('tracker-ci-all', 'ci')):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url, {'date': '2026-10-12'}).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url, {'date': '2026-10-12'}).status_code, 401)

    def test_circle_scope_limits_every_figure(self):
        self.store(OD_4G, date(2026, 10, 12))
        body = arrivals.tracker(date(2026, 10, 12), {'MP'})
        self.assertEqual([(i['project'], i['circle']) for i in body['items']], [('4G Saturation', 'MP')])
        self.assertEqual(arrivals.tracker(date(2026, 10, 12), set())['items'], [])

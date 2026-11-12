"""Approved business rules B-1/B-2 (reporting units), B-5 (On-Air eligibility), B-6 (coverage threshold) and B-7 (missing
data, finalization) in apps.sitedata.reporting, dataset/portfolio and the Admin API. Test database only."""
from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.sitedata import arrivals, dashboard_source, portfolio, reporting
from apps.sitedata.models import CoverageThreshold, MonthFinalization, MonthlySitePerformance, ReportingUnit, ReportingUnitChange
from tests.auth_helpers import portal_user
from tests.sitedata_factory import make_daily, make_site, make_unit

G4, LWE = '4G Saturation', 'LWE'
OCT = [date(2026, 10, d) for d in range(1, 32)]


class ReportingTestCase(TestCase):
    def setUp(self):
        portfolio.clear_cache()
        self.addCleanup(portfolio.clear_cache)
        self.admin = portal_user('rules-admin', 'admin')
        # MP has 4G and LWE; RJ has 4G only.
        self.mp4 = make_site('UVMP001', technology=G4, circle='MP', on_air_date=date(2026, 1, 1))
        self.mp4b = make_site('UVMP002', technology=G4, circle='MP', on_air_date=date(2026, 10, 3))  # On-Air from 3 Oct
        self.mpl = make_site('LWEMP01', technology=LWE, circle='MP', on_air_date=date(2026, 1, 1))
        self.rj4 = make_site('UVRJ001', technology=G4, circle='RJ', on_air_date=date(2026, 1, 1))

    def fill(self, sites, days, outage=0):
        for s in sites:
            for d in days:
                make_daily(s, d, outage)
        portfolio.clear_cache()


class ExpectedUnitTests(ReportingTestCase):
    def test_a_unit_activated_mid_month_is_expected_only_from_its_activation_date(self):
        make_unit(LWE, 'RJ', active_from=date(2026, 10, 5))
        make_site('LWERJ01', technology=LWE, circle='RJ', on_air_date=date(2026, 1, 1), unit=False)
        cov = reporting.coverage([date(2026, 10, 4), date(2026, 10, 5)])
        self.assertNotIn((LWE, 'RJ'), cov[date(2026, 10, 4)])
        self.assertIn((LWE, 'RJ'), cov[date(2026, 10, 5)])
        self.assertFalse(cov[date(2026, 10, 5)][(LWE, 'RJ')]['covered'])  # expected, no data yet

    def test_a_deactivated_unit_is_no_longer_expected_and_never_blanks_the_dashboard(self):
        self.fill([self.mp4, self.mpl, self.rj4], OCT[:4])
        ReportingUnit.objects.filter(technology=LWE, circle='MP').update(active_until=date(2026, 10, 2))
        self.fill([self.mp4, self.mp4b, self.rj4], [date(2026, 10, 5)])
        cov = reporting.coverage([date(2026, 10, 5)])
        self.assertNotIn((LWE, 'MP'), cov[date(2026, 10, 5)])
        ds = dashboard_source.dataset()
        self.assertEqual(ds.reported_dates[-1], date(2026, 10, 5))
        self.assertEqual(dashboard_source.continuity(ds)['date_status'][-1]['status'], 'Complete')

    def test_a_new_unit_never_invalidates_earlier_dates(self):
        # The audit's critical defect (C-1): a new unit starting mid-month blanked every date.
        self.fill([self.mp4, self.mpl, self.rj4], OCT[:3])
        make_unit(LWE, 'OD', active_from=date(2026, 10, 3))
        od = make_site('LWEOD01', technology=LWE, circle='OD', on_air_date=date(2026, 1, 1), unit=False)
        self.fill([od], [date(2026, 10, 3)])
        ds = dashboard_source.dataset()
        self.assertEqual(ds.reported_dates, (date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)))
        status = {s['date']: s['status'] for s in dashboard_source.continuity(ds)['date_status']}
        self.assertEqual(status['2026-10-01'], 'Complete')


class OnAirEligibilityTests(ReportingTestCase):
    def test_a_site_is_expected_only_from_its_on_air_date(self):
        cov = reporting.coverage([date(2026, 10, 2), date(2026, 10, 3)])
        self.assertEqual(cov[date(2026, 10, 2)][(G4, 'MP')]['expected'], 1)
        self.assertEqual(cov[date(2026, 10, 3)][(G4, 'MP')]['expected'], 2)

    def test_a_retrospective_on_air_correction_changes_the_results(self):
        self.fill([self.mp4], OCT[:3])
        self.assertFalse(reporting.coverage([date(2026, 10, 3)])[date(2026, 10, 3)][(G4, 'MP')]['covered'])  # UVMP002 missing
        self.mp4b.on_air_date = date(2026, 11, 1)  # corrected in the matrix
        self.mp4b.save()
        self.assertTrue(reporting.coverage([date(2026, 10, 3)])[date(2026, 10, 3)][(G4, 'MP')]['covered'])


class IndependenceAndMissingDataTests(ReportingTestCase):
    def test_missing_lwe_never_blocks_4g_and_is_never_zero(self):
        self.fill([self.mp4, self.mp4b, self.rj4], OCT[:5])
        self.fill([self.mpl], OCT[:2])  # LWE MP missing from 3 Oct
        ds = dashboard_source.dataset()
        self.assertEqual(ds.reported_dates[-1], date(2026, 10, 5))
        g4 = dashboard_source.dataset({(G4, 'MP'), (G4, 'RJ')})
        lwe = dashboard_source.dataset({(LWE, 'MP')})
        self.assertEqual(dashboard_source.continuity(g4)['mtd_status'], 'Complete')
        self.assertEqual(dashboard_source.continuity(lwe)['mtd_status'], 'Provisional')
        self.assertEqual(lwe.reported_dates[-1], date(2026, 10, 2))  # LWE shows its own data only
        i = ds.position(date(2026, 10, 4))
        row = list(ds.sites['site_id']).index('LWEMP01')
        self.assertTrue(ds.outage[row, i] != ds.outage[row, i])  # NaN: not reported, not zero

    def test_late_arriving_data_makes_the_date_complete(self):
        self.fill([self.mp4, self.mp4b, self.rj4], OCT[:3])
        self.assertIn('2026-10-03', dashboard_source.continuity(dashboard_source.dataset())['incomplete_dates'])
        self.fill([self.mpl], OCT[:3])
        self.assertEqual(dashboard_source.continuity(dashboard_source.dataset())['incomplete_dates'], [])


class CoverageThresholdTests(ReportingTestCase):
    def test_threshold_is_effective_dated_and_keeps_history(self):
        self.client.force_login(self.admin)
        today = timezone.localdate()
        r = self.client.post(reverse('sitedata-coverage-threshold'), {'value_pct': 50, 'effective_from': '2026-10-02', 'reason': 'policy'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)  # retroactive: needs confirmation
        self.assertIn('confirm_retroactive', r.json()['details'])
        r = self.client.post(reverse('sitedata-coverage-threshold'), {'value_pct': 50, 'effective_from': '2026-10-02', 'reason': 'policy',
                                                                     'confirm_retroactive': True}, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['previous_value_pct'], 100.0)
        self.assertEqual(reporting.threshold_on(date(2026, 10, 1)), 100.0)  # earlier dates keep their threshold
        self.assertEqual(reporting.threshold_on(date(2026, 10, 2)), 50.0)
        # 1 of 2 MP 4G sites on 3 Oct: covered at 50 %, not at 100 %.
        self.fill([self.mp4], [date(2026, 10, 3)])
        self.assertTrue(reporting.coverage([date(2026, 10, 3)])[date(2026, 10, 3)][(G4, 'MP')]['covered'])
        history = self.client.get(reverse('sitedata-coverage-threshold')).json()['history']
        self.assertEqual([h['value_pct'] for h in history], [50.0, 100.0])
        self.assertEqual(history[0]['changed_by'], self.admin.get_username())
        self.assertGreaterEqual(reporting.threshold_on(today), 50.0)

    def test_threshold_cannot_rewrite_a_finalized_month(self):
        MonthFinalization.objects.create(month=date(2026, 10, 1), status='complete')
        self.client.force_login(self.admin)
        r = self.client.post(reverse('sitedata-coverage-threshold'), {'value_pct': 80, 'effective_from': '2026-10-15', 'reason': 'x',
                                                                     'confirm_retroactive': True}, content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('effective_from', r.json()['details'])
        self.assertEqual(CoverageThreshold.objects.count(), 1)


class ReportingUnitApiTests(ReportingTestCase):
    def test_add_correct_deactivate_and_reactivate_with_an_audit_trail(self):
        self.client.force_login(self.admin)
        url = reverse('sitedata-reporting-units')
        self.assertEqual(self.client.post(url, {'technology': LWE, 'circle': 'RJ', 'active_from': '2026-11-01'}, content_type='application/json').status_code, 400)
        r = self.client.post(url, {'technology': LWE, 'circle': 'RJ', 'active_from': '2026-11-01', 'reason': 'new LWE sites'}, content_type='application/json')
        self.assertIn(r.status_code, (201, 400))  # 400 when LWE RJ is not set up in the Organization
        if r.status_code == 400:
            self.assertIn('Organization', str(r.json()))
        unit = ReportingUnit.objects.get(technology=G4, circle='RJ')
        detail = reverse('sitedata-reporting-unit', args=[unit.pk])
        self.assertEqual(self.client.patch(detail, {'active_until': '2026-10-31'}, content_type='application/json').status_code, 400)  # reason needed
        self.assertEqual(self.client.patch(detail, {'active_until': '2026-10-31', 'reason': 'circle closed'}, content_type='application/json').status_code, 200)
        self.assertEqual(self.client.patch(detail, {'active_until': None, 'reason': 'reopened'}, content_type='application/json').status_code, 200)
        actions = list(ReportingUnitChange.objects.filter(unit=unit).order_by('id').values_list('action', flat=True))
        self.assertEqual(actions[-2:], ['deactivated', 'reactivated'])
        self.client.force_login(portal_user('rules-ci', 'ci'))
        self.assertEqual(self.client.get(url).status_code, 403)


class FinalizationTests(ReportingTestCase):
    def test_a_month_with_missing_data_finalizes_as_incomplete_and_can_be_reopened(self):
        self.fill([self.mp4, self.mp4b, self.rj4], OCT)
        self.fill([self.mpl], OCT[:20])  # LWE MP missing 21-31 Oct
        self.client.force_login(self.admin)
        r = self.client.post(reverse('sitedata-months-finalize'), {'month': '2026-10-01', 'confirm': True}, content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        final = r.json()['finalization']
        self.assertEqual((final['status'], final['status_label']), ('incomplete_missing_data', 'Incomplete — Missing Data'))
        self.assertEqual([(m['technology'], m['circle'], len(m['dates'])) for m in final['missing']], [(LWE, 'MP', 11)])
        self.assertTrue(MonthlySitePerformance.objects.filter(month=date(2026, 10, 1), finalized_at__isnull=False).exists())
        months = {m['month']: m for m in self.client.get(reverse('sitedata-months')).json()['months']}
        self.assertEqual(months['2026-10-01']['finalization_label'], 'Incomplete — Missing Data')
        # Late data is refused until an Admin reopens the month (controlled, audited).
        self.assertEqual(self.client.post(reverse('sitedata-months-reopen'), {'month': '2026-10-01'}, content_type='application/json').status_code, 400)
        r = self.client.post(reverse('sitedata-months-reopen'), {'month': '2026-10-01', 'reason': 'late LWE MP files'}, content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(MonthlySitePerformance.objects.filter(month=date(2026, 10, 1), finalized_at__isnull=False).exists())
        self.fill([self.mpl], OCT[20:])
        r = self.client.post(reverse('sitedata-months-finalize'), {'month': '2026-10-01', 'confirm': True}, content_type='application/json')
        self.assertEqual((r.json()['finalization']['status'], r.json()['finalization']['revision']), ('complete', 2))
        self.assertEqual(MonthFinalization.objects.filter(month=date(2026, 10, 1)).count(), 2)  # both kept


class ArrivalTrackerRuleTests(ReportingTestCase):
    def test_tracker_uses_active_units_and_the_threshold(self):
        self.fill([self.mp4, self.rj4, self.mpl], [date(2026, 10, 3)])  # UVMP002 (On-Air 3 Oct) missing
        items = {(i['project'], i['circle']): i for i in arrivals.tracker(date(2026, 10, 3), None)['items']}
        self.assertEqual(items[(G4, 'MP')]['data_state'], 'partial')
        self.assertEqual(items[(G4, 'MP')]['coverage_threshold_pct'], 100.0)
        self.assertEqual(items[(G4, 'RJ')]['data_state'], 'complete')
        ReportingUnit.objects.filter(technology=G4, circle='RJ').update(active_until=date(2026, 10, 1))
        items = {(i['project'], i['circle']): i for i in arrivals.tracker(date(2026, 10, 3), None)['items']}
        self.assertEqual((items[(G4, 'RJ')]['data_state'], items[(G4, 'RJ')]['active']), ('no_scope', False))

"""Consolidated Escalation Matrix: parsing, preview / commit, links to the Up-Time sites and the cross-check."""
import tempfile
from datetime import date, datetime
from pathlib import Path

from django.db import connection
from django.test import TestCase, override_settings
from openpyxl import Workbook

from apps.dashboard.activity import CIRCLES
from apps.rca.models import RcaRecord
from apps.uptimedb import escalation
from apps.uptimedb.models import DataImportBatch, EscalationImportBatch, EscalationSite, SiteMonthlyPerformance, UptimeSite

HEADER = ['SL', 'Entity', 'Site Type', 'Circle Name', 'BSNL Site ID', 'Site Name/Village Name', 'BA', 'OA', 'District',
          'Site Commissioning /Hoto Date', 'O&M Status', 'O&M Start Date', 'EB Status', 'Site On Air Status', 'Site On Air Date',
          'IE Name', 'IE Contact', 'CI Name', 'CI Contact', 'IL Name', 'Contact', 'CBH Name', 'Contact', 'Lattitude', 'Longitude',
          'Rigger Name', 'Contact', '@', 'Combo', None]
ROWS = [
    # Matched; the CI name differs only in case and spacing (not a difference), the IE name really differs.
    [1, '4G Saturation', '4G Saturation', 'Madhya Pradesh', ' uvmp001 ', 'Alpha', 'BHOPAL', 'SEHORE', 'Sehore',
     datetime(2024, 4, 30), 'Yes', datetime(2025, 10, 1), 'EB', 'Yes', datetime(2024, 7, 19),
     'IE Other', 9000000001, 'ci  east', 9000000002, 'IL One', 9000000003, 'CBH One', 9000000004, 23.25, 77.4,
     'Rig One', 9000000005, 'Mr. _', 'Mr. _IE_MB:-1', None],
    # Misspelled circle (Chattishgarh -> CG); text in a date column; 0 coordinates; On-Air differs.
    [2, 'LWE', 'LWE', 'Chattishgarh', 'LWECG0001', 'Beta', 'RAIPUR', 'RAIPUR', 'Raipur', 'NO', 'Yes', '-', 'N-EB', None,
     None, 'IE CG', 1, 'CI CG', 2, 'Vacant', '-', 'CBH Two', 3, 0, 0, None, None, 'Mr. _', 'x', 'Connection Done Sites'],
    # Not in the Up-Time Report.
    [3, 'LWE', 'LWE', 'Telangna', 'LWETL0009', 'Gamma', 'X', 'Y', 'Z', None, None, None, 'EB', 'Yes', datetime(2025, 1, 1),
     'IE TL', 1, 'CI TL', 2, '-', '-', '-', '-', 17.1, 79.2, None, None, '@', 'x', None],
    # Another entity: stored, never matched.
    [4, 'VI-HPSC', 'BSNL Own', 'Delhi-NCR', 'VIDL001', 'Delta', 'D', 'D', 'D', None, None, None, 'EB', 'Yes', None,
     '-', '-', '-', '-', '-', '-', '-', '-', 28.6, 77.2, None, None, '@', 'x', None],
]


def write_matrix(path: Path, rows=ROWS) -> Path:
    book = Workbook()
    book.active.title = 'Summary'
    sheet = book.create_sheet('Raw Data')
    sheet.append(['Consolidated Escalation Matrix'])
    sheet.append([])
    sheet.append(HEADER)
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


class EscalationTestCase(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        override = override_settings(DATA_DIR=Path(self._tmp.name))
        override.enable()
        self.addCleanup(override.disable)
        self.path = write_matrix(Path(self._tmp.name) / 'matrix.xlsx')
        batch = DataImportBatch.objects.create(original_filename='master.xlsx', checksum_sha256='x', sheet_name='Up-Time Report',
                                               stored_path='-', status=DataImportBatch.Status.COMMITTED)

        def site(project, circle, site_id, **kw):
            return UptimeSite.objects.create(project=project, circle=circle, site_id=site_id, site_key=site_id.upper(),
                                             batch=batch, source_row=1, **kw)
        self.mp = site('4G Saturation', 'MP', 'UVMP001', ci_name='CI East', ie_name='IE MP', on_air=True)
        self.cg = site('LWE', 'CG', 'LWECG0001', ci_name='CI CG', ie_name='IE CG', on_air=True)
        self.lonely = site('4G Saturation', 'RJ', 'UVRJ999', on_air=True)
        SiteMonthlyPerformance.objects.create(site=self.mp, month=date(2026, 10, 1), om_start=True, batch=batch)
        SiteMonthlyPerformance.objects.create(site=self.cg, month=date(2026, 10, 1), om_start=False, batch=batch)

    def imported(self, path=None):
        return escalation.commit(escalation.preview(path or self.path, 'matrix.xlsx'))


class ParseTests(EscalationTestCase):
    def test_fields_contacts_dates_and_circles(self):
        sites = escalation.parse(self.path, 'matrix.xlsx')['sites']
        mp = sites[('4G Saturation', 'UVMP001')]
        self.assertEqual((mp['site_id'], mp['circle'], mp['on_air_date'], mp['om_start_date']),
                         ('uvmp001', 'MP', date(2024, 7, 19), date(2025, 10, 1)))
        # Each "Contact" belongs to the person named before it.
        self.assertEqual((mp['il_contact'], mp['cbh_contact'], mp['rigger_contact']), ('9000000003', '9000000004', '9000000005'))
        cg = sites[('LWE', 'LWECG0001')]
        self.assertEqual((cg['circle'], cg['circle_raw']), ('CG', 'Chattishgarh'))
        self.assertEqual((cg['commissioning_date'], cg['commissioning_raw'], cg['om_start_date'], cg['om_start_raw']), (None, 'NO', None, '-'))
        self.assertEqual((cg['latitude'], cg['longitude']), (None, None))  # 0 is a placeholder, not a position
        self.assertEqual(cg['extra'], {'Column AD': 'Connection Done Sites'})
        self.assertNotIn('@', mp['extra'])  # formatting helpers are not stored
        self.assertEqual(sites[('LWE', 'LWETL0009')]['circle'], 'TL')
        self.assertEqual(sites[('VI-HPSC', 'VIDL001')]['project'], 'VI-HPSC')

    def test_activity_uses_the_same_circle_spellings(self):
        for name, code in (('chattishgarh', 'CG'), ('maharastra', 'MH'), ('telangna', 'TL'), ('west bangal', 'WB')):
            self.assertEqual(CIRCLES[name], code)

    def test_values_too_long_for_their_column_are_rejected_in_the_preview(self):
        rows = [list(ROWS[0])]
        rows[0][5] = 'x' * 201  # site name, limit 200
        with self.assertRaisesRegex(escalation.EscalationRejected, 'site_name'):
            escalation.parse(write_matrix(Path(self._tmp.name) / 'long.xlsx', rows), 'long.xlsx')

    def test_a_file_without_the_sheet_is_rejected(self):
        path = Path(self._tmp.name) / 'other.xlsx'
        Workbook().save(path)
        with self.assertRaises(escalation.EscalationRejected):
            escalation.parse(path, 'other.xlsx')


class ImportTests(EscalationTestCase):
    def test_preview_writes_no_sites_and_cross_checks(self):
        batch = escalation.preview(self.path, 'matrix.xlsx')
        self.assertEqual(EscalationSite.objects.count(), 0)
        check = batch.report['cross_check']
        self.assertEqual({k: check[k]['count'] for k in ('matched', 'not_in_uptime', 'other_entity', 'ci_name_differs',
                                                          'ie_name_differs', 'on_air_differs', 'om_start_differs')},
                         {'matched': 2, 'not_in_uptime': 1, 'other_entity': 1, 'ci_name_differs': 0, 'ie_name_differs': 1,
                          'on_air_differs': 1, 'om_start_differs': 1})
        self.assertEqual(check['ie_name_differs']['examples'][0], {'site_id': 'uvmp001', 'matrix': 'IE Other', 'uptime_report': 'IE MP'})
        self.assertEqual(check['uptime_sites_not_in_matrix']['examples'], [{'site_id': 'UVRJ999', 'project': '4G Saturation', 'circle': 'RJ'}])
        self.assertEqual(batch.report['database_effect']['new'], 4)

    def test_commit_stores_and_links_and_is_idempotent(self):
        batch = self.imported()
        self.assertEqual(batch.counts['inserted'], 4)
        self.assertEqual(batch.counts['links'], {'matched': 2, 'not_in_uptime': 1, 'other_entity': 1})
        self.assertEqual(self.mp.escalation.cbh_name, 'CBH One')
        self.assertEqual(EscalationSite.objects.get(site_key='LWECG0001').uptime_site, self.cg)
        again = self.imported()
        self.assertEqual((again.counts['inserted'], again.counts['updated'], again.counts['unchanged']), (0, 0, 4))

    def test_changed_rows_are_updated_and_missing_rows_kept(self):
        self.imported()
        rows = [list(ROWS[0])]
        rows[0][21] = 'CBH New'
        changed = self.imported(write_matrix(Path(self._tmp.name) / 'matrix2.xlsx', rows))
        self.assertEqual((changed.counts['updated'], changed.counts['not_in_this_file']), (1, 3))
        self.assertEqual(EscalationSite.objects.count(), 4)
        self.assertEqual(EscalationSite.objects.get(site_key='UVMP001').cbh_name, 'CBH New')

    def test_sites_added_later_are_linked(self):
        self.imported()
        batch = DataImportBatch.objects.first()
        added = UptimeSite.objects.create(project='LWE', circle='TL', site_id='LWETL0009', site_key='LWETL0009', batch=batch, source_row=2)
        escalation.link_uptime_sites()
        self.assertEqual(EscalationSite.objects.get(site_key='LWETL0009').uptime_site, added)

    def test_a_changed_staged_file_cannot_be_committed(self):
        batch = escalation.preview(self.path, 'matrix.xlsx')
        Path(batch.stored_path).write_bytes(b'changed')
        with self.assertRaises(escalation.EscalationRejected):
            escalation.commit(batch)
        self.assertEqual(EscalationImportBatch.objects.get(pk=batch.pk).status, 'previewed')

    def test_site_overview_view_joins_uptime_escalation_and_rca(self):
        self.imported()
        RcaRecord.objects.create(reporting_date=date(2026, 10, 21), project='4G Saturation', project_raw='4G', circle='MP',
                                 circle_raw='MP', site_id='UVMP001', site_key='UVMP001')
        with connection.cursor() as cursor:
            cursor.execute('SELECT site_id, cbh_name, on_air_date, rca_records FROM site_overview ORDER BY site_id')
            rows = cursor.fetchall()
        self.assertEqual([(r[0], r[1], r[3]) for r in rows], [('LWECG0001', 'CBH Two', 0), ('UVMP001', 'CBH One', 1), ('UVRJ999', None, 0)])
        self.assertEqual(str(rows[1][2]), '2024-07-19')

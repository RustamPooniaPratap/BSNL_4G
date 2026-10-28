"""O&M Head names from the "first page" reference sheet."""
import tempfile
from pathlib import Path

from django.test import override_settings
from django.urls import reverse
from openpyxl import Workbook

from .auth_helpers import SignedInTestCase


class OmHeadTests(SignedInTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name)
        self._override = override_settings(DATA_DIR=self.data)
        self._override.enable()

    def tearDown(self):
        self._override.disable()
        self._tmp.cleanup()
        super().tearDown()

    def sheet(self, rows):
        book = Workbook()
        ws = book.active
        ws.append([None, None, None, None, 6717, 6417])  # totals strip
        ws.append([None, 'Circle', 'Client', 'O&M Head', 'Site Scope'])
        for row in rows:
            ws.append(row)
        (self.data / 'reference').mkdir(parents=True, exist_ok=True)
        book.save(self.data / 'reference' / 'BSNL 4G - first page.xlsx')

    def test_names_are_read_with_circle_codes_mapped_and_dashes_left_empty(self):
        self.sheet([[None, 'RAJ', '4G Sat', 'Upendra Singh', 1457], [None, None, None, None, 4543],  # subtotal row skipped
                    [None, 'BR', 'LWE', 'Sanjeev Ranjan', 250], [None, 'AP', 'LWE', '-', 62]])
        data = self.client.get(reverse('dashboard-om-heads')).json()
        self.assertEqual(data['source'], 'BSNL 4G - first page.xlsx')
        self.assertEqual([(h['report_type'], h['circle'], h['om_head']) for h in data['heads']],
                         [('4G Saturation', 'RJ', 'Upendra Singh'), ('LWE', 'BH', 'Sanjeev Ranjan'), ('LWE', 'AP', None)])

    def test_without_the_sheet_nothing_is_invented(self):
        data = self.client.get(reverse('dashboard-om-heads')).json()
        self.assertEqual((data['source'], data['heads']), (None, []))
        self.assertIn('No reference sheet', data['message'])

    def test_signed_out_users_are_refused(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('dashboard-om-heads')).status_code, 401)

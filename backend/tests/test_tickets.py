from io import BytesIO
from contextlib import contextmanager
from pathlib import Path
from xml.etree import ElementTree
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.accounts.models import AccessAssignment, Role, RolePermission
from apps.organization.models import Circle, CircleAlias, Project, ProjectCircle
from apps.tickets import importer, parser
from apps.tickets.models import Ticket, TicketEvent, TicketNotification
from apps.alerts.mailer import MailError
from tests.auth_helpers import portal_user
from tests.sitedata_factory import make_site


def workbook(rows, headers=None):
    output = BytesIO()
    book = Workbook()
    sheet = book.active
    sheet.title = 'Ticket_Upload'
    sheet.append(headers or parser.HEADERS)
    for row in rows:
        sheet.append(row)
    book.save(output)
    return output.getvalue()


def formula_workbook(rows, cached_results=None):
    source = BytesIO(workbook(rows))
    result = BytesIO()
    namespace = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with ZipFile(source) as source_zip, ZipFile(result, 'w', ZIP_DEFLATED) as result_zip:
        for item in source_zip.infolist():
            contents = source_zip.read(item.filename)
            if item.filename == 'xl/worksheets/sheet1.xml':
                root = ElementTree.fromstring(contents)
                for cell_reference, cached_value in (cached_results or {}).items():
                    cell = root.find(f".//{namespace}c[@r='{cell_reference}']")
                    if cell is None:
                        raise AssertionError(f'No formula cell at {cell_reference}.')
                    value = cell.find(f'{namespace}v')
                    if value is None:
                        value = ElementTree.SubElement(cell, f'{namespace}v')
                    value.text = str(cached_value)
                contents = ElementTree.tostring(root, encoding='utf-8', xml_declaration=True)
            result_zip.writestr(item, contents)
    return result.getvalue()


def ticket_row(*, status='Open', email='dispatch@example.com', site_name='Test Site', serial='1'):
    return [
        serial, '2026-11-04', 'MP', 'MP-TST-001', site_name, 'Bhopal', 'Bhopal BA',
        '2026-11-04 02:15:00', '2026-11-04 02:30:00', '2026-11-04 04:45:00',
        150, '02:30:00', 'Vendor A', 'OFC Cut', 'Fiber cut near highway', status, email,
    ]


@contextmanager
def successful_mail():
    with patch('apps.tickets.services.engine.active_account', return_value=object()):
        with patch('apps.tickets.services.mailer.send', return_value='250 accepted'):
            yield


class TicketImportTests(TestCase):
    def setUp(self):
        self.user = portal_user('ticket-admin', 'admin')
        self.client.force_login(self.user)
        project, _ = Project.objects.get_or_create(key='4G Saturation', defaults={'code': '4G', 'name': '4G Saturation'})
        circle, _ = Circle.objects.get_or_create(code='MP', defaults={'name': 'Madhya Pradesh'})
        ProjectCircle.objects.get_or_create(project=project, circle=circle)
        self.site = make_site('MP-TST-001', technology=project.key, circle=circle.code, site_name='Test Site')

    def preview(self, rows, name='tickets.xlsx'):
        return importer.preview(workbook(rows), name, self.user)

    def commit(self, batch, **options):
        return importer.commit(batch.pk, self.user, **options)

    def send_mail(self):
        return successful_mail()

    def test_parser_rejects_reordered_or_duplicate_headers_and_skips_reserved_example(self):
        reordered = list(parser.HEADERS)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        with self.assertRaisesRegex(parser.WorkbookError, 'Column order'):
            parser.parse_workbook(workbook([ticket_row()], reordered))

        duplicated = list(parser.HEADERS)
        duplicated[-1] = 'Date'
        with self.assertRaisesRegex(parser.WorkbookError, 'Duplicate'):
            parser.parse_workbook(workbook([ticket_row()], duplicated))

        template = Path(__file__).resolve().parents[2] / 'Data' / 'reference' / 'BSNL_Ticket_Upload_Template (1).xlsx'
        parsed = parser.parse_workbook(template.read_bytes())
        self.assertEqual(parsed['counts']['sample_rows_skipped'], 1)
        self.assertEqual(parsed['rows'][0]['outcome'], 'sample_skipped')
        self.assertNotIn('values', parsed['rows'][0])

    def test_numeric_duration_is_hours_and_invalid_clock_parts_are_rejected(self):
        self.assertEqual(parser._decimal(0.5, duration=True), 0.5)
        with self.assertRaises(ValueError):
            parser._decimal('01:75:00', duration=True)

    def test_numeric_literal_outage_minutes_and_mttr_keep_existing_validation(self):
        row = ticket_row()
        row[10], row[11] = 123.45, 2.5
        parsed = parser.parse_workbook(workbook([row]))
        self.assertEqual(parsed['rows'][0]['outcome'], 'valid')
        self.assertEqual(parsed['rows'][0]['values']['outage_minutes'], '123.45')
        self.assertEqual(parsed['rows'][0]['values']['mttr_hours'], '2.5')

    def test_computed_precision_artifacts_are_normalized_but_unrelated_precision_is_rejected(self):
        row = ticket_row()
        row[7], row[9] = '2026-11-04 00:00:00', '2026-11-04 02:05:00'
        row[10], row[11] = 125.000000003, 2.08333333338
        parsed = parser.parse_workbook(workbook([row]))
        parsed_row = parsed['rows'][0]
        self.assertEqual(parsed_row['outcome'], 'valid')
        self.assertEqual(parsed_row['values']['outage_minutes'], '125.00')
        self.assertEqual(parsed_row['values']['mttr_hours'], '2.0833')
        self.assertEqual(parsed_row['source_values']['Outage Min.'], '125.00')
        self.assertEqual(parsed_row['source_values']['MTTR (Hrs.)'], '2.0833')

        row = ticket_row()
        row[10], row[11] = 123.456, 2.057612
        parsed = parser.parse_workbook(workbook([row]))
        self.assertEqual([error['field'] for error in parsed['rows'][0]['errors']],
                         ['Outage Min.', 'MTTR (Hrs.)'])

    def test_formula_cells_use_cached_numeric_results_and_preview_api_returns_them(self):
        row = ticket_row()
        row[10], row[11] = '=1+2', '=5/2'
        contents = formula_workbook([row], {'K2': '3.25', 'L2': '2.5'})

        parsed = parser.parse_workbook(contents)
        parsed_row = parsed['rows'][0]
        self.assertEqual(parsed_row['outcome'], 'valid')
        self.assertEqual(parsed_row['values']['outage_minutes'], '3.25')
        self.assertEqual(parsed_row['values']['mttr_hours'], '2.5')
        self.assertEqual(parsed_row['source_values']['Outage Min.'], '3.25')
        self.assertEqual(parsed_row['source_values']['MTTR (Hrs.)'], '2.5')

        response = self.client.post(
            reverse('ticket-import-preview'),
            {'file': SimpleUploadedFile('formula-tickets.xlsx', contents,
                                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
        )
        self.assertEqual(response.status_code, 201, response.content)
        response_row = response.json()['rows'][0]
        self.assertEqual(response_row['outcome'], 'create')
        self.assertEqual(response_row['values']['outage_minutes'], '3.25')
        self.assertEqual(response_row['values']['mttr_hours'], '2.5')
        self.assertEqual(response_row['source_values']['Outage Min.'], '3.25')

    def test_formula_cells_without_cached_results_get_one_field_specific_error(self):
        row = ticket_row()
        row[10], row[11] = '=1+2', '=5/2'
        contents = formula_workbook([row])
        parsed = parser.parse_workbook(contents)
        errors = parsed['rows'][0]['errors']
        self.assertEqual([error['field'] for error in errors], ['Outage Min.', 'MTTR (Hrs.)'])
        self.assertTrue(all('Formula result is unavailable.' in error['message'] for error in errors))
        self.assertTrue(all('Formula cells are not supported' not in error['message'] for error in errors))

        response = self.client.post(
            reverse('ticket-import-preview'),
            {'file': SimpleUploadedFile('uncalculated.xlsx', contents,
                                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
        )
        self.assertEqual(response.status_code, 201, response.content)
        response_row = response.json()['rows'][0]
        self.assertEqual(response_row['excel_row'], 2)
        self.assertEqual([error['field'] for error in response_row['errors']], ['Outage Min.', 'MTTR (Hrs.)'])

    def test_negative_and_overprecision_formula_results_use_numeric_validation(self):
        for cached, expected_fields in (
            ({'K2': '-1', 'L2': '-2'}, ['Outage Min.', 'MTTR (Hrs.)']),
            ({'K2': '1.234', 'L2': '1.23456'}, ['Outage Min.', 'MTTR (Hrs.)']),
        ):
            row = ticket_row()
            row[10], row[11] = '=1+2', '=5/2'
            parsed = parser.parse_workbook(formula_workbook([row], cached))
            errors = parsed['rows'][0]['errors']
            self.assertEqual([error['field'] for error in errors], expected_fields)
            self.assertTrue(all('Formula cells are not supported' not in error['message'] for error in errors))

    def test_blank_numeric_cells_remain_valid(self):
        row = ticket_row()
        row[10] = row[11] = None
        parsed = parser.parse_workbook(workbook([row]))
        self.assertEqual(parsed['rows'][0]['outcome'], 'valid')
        self.assertEqual(parsed['rows'][0]['values']['outage_minutes'], '')
        self.assertEqual(parsed['rows'][0]['values']['mttr_hours'], '')

    def test_multiple_formula_rows_and_overnight_datetimes_are_preserved(self):
        first = ticket_row()
        first[10], first[11] = '=1+2', '=5/2'
        second = ticket_row(serial='2')
        second[3] = 'MP-TST-002'
        second[7], second[9] = '2026-11-04 23:30:00', '2026-11-05 02:15:00'
        second[10], second[11] = '=1+2', '=5/2'
        parsed = parser.parse_workbook(formula_workbook(
            [first, second],
            {'K2': '150', 'L2': '2.5', 'K3': '165.000000003', 'L3': '2.75000000005'},
        ))
        self.assertEqual(parsed['counts']['valid_rows'], 2)
        self.assertEqual(parsed['rows'][1]['values']['outage_minutes'], '165.00')
        self.assertEqual(parsed['rows'][1]['values']['mttr_hours'], '2.7500')
        self.assertEqual(parsed['rows'][1]['values']['actual_down_time'], '2026-11-04 23:30:00')
        self.assertEqual(parsed['rows'][1]['values']['restoration_time'], '2026-11-05 02:15:00')

    def test_compact_restoration_datetime_in_supplied_workbook_format(self):
        row = ticket_row()
        row[1] = '2026-11-09'
        row[7] = '2026-11-09 00:00:00'
        row[9] = '09-11-202623:59:00'
        row[10], row[11] = 1439, 23.983333333333334
        parsed = parser.parse_workbook(workbook([row]))
        parsed_row = parsed['rows'][0]
        self.assertEqual(parsed_row['outcome'], 'valid')
        self.assertEqual(parsed_row['values']['restoration_time'], '2026-11-09 23:59:00')
        self.assertEqual(parsed_row['values']['mttr_hours'], '23.9833')

    def test_formula_cells_are_rejected_instead_of_silently_using_blank_cached_values(self):
        row = ticket_row()
        row[4] = '=CONCAT("Test"," Site")'
        parsed = parser.parse_workbook(workbook([row]))
        self.assertEqual(parsed['rows'][0]['outcome'], 'invalid')
        self.assertEqual(parsed['rows'][0]['errors'][0]['field'], 'Site Name')

    def test_open_ticket_is_persisted_with_a_per_row_notification_and_event_history(self):
        batch = self.preview([ticket_row()])
        with self.send_mail():
            committed = self.commit(batch)

        ticket = Ticket.objects.get()
        notification = TicketNotification.objects.get()
        self.assertEqual(committed.counts['new_tickets'], 1)
        self.assertTrue(ticket.portal_ticket_id.startswith('OFC-'))
        self.assertEqual(ticket.status, 'Open')
        self.assertEqual(ticket.master_site, self.site)
        self.assertEqual(notification.recipient, 'dispatch@example.com')
        self.assertEqual(notification.status, TicketNotification.Status.ACCEPTED)
        self.assertEqual(notification.attempt_log.get().accepted, True)
        self.assertEqual(TicketEvent.objects.filter(ticket=ticket).count(), 2)

    def test_mail_failure_does_not_roll_back_ticket_or_import(self):
        batch = self.preview([ticket_row()])
        with patch('apps.tickets.services.engine.active_account', return_value=object()):
            with patch('apps.tickets.services.mailer.send', side_effect=MailError('SMTP unavailable')):
                committed = self.commit(batch)
        ticket = Ticket.objects.get()
        notification = TicketNotification.objects.get(ticket=ticket)
        self.assertEqual(committed.status, 'committed')
        self.assertEqual(ticket.status, 'Open')
        self.assertEqual(notification.status, TicketNotification.Status.FAILED)
        self.assertEqual(notification.attempt_log.get().detail, 'SMTP unavailable')

    def test_project_specific_circle_alias_resolves_against_site_project(self):
        project = Project.objects.get(key='4G Saturation')
        CircleAlias.objects.create(source=CircleAlias.Source.TICKET_UPLOAD, project=project, raw_code='Central Region',
                                   raw_key='central region', circle=Circle.objects.get(code='MP'))
        row = ticket_row()
        row[2] = 'Central Region'
        batch = self.preview([row])
        self.assertEqual(batch.counts['invalid_rows'], 0)
        self.assertEqual(batch.counts['new_tickets'], 1)

    def test_reimport_updates_same_ticket_closes_and_reopens_without_duplicate_ids(self):
        first = self.preview([ticket_row()])
        with self.send_mail():
            self.commit(first)
        ticket = Ticket.objects.get()
        portal_id = ticket.portal_ticket_id

        update = self.preview([ticket_row(site_name='Updated Site', email='new@example.com')], name='update.xlsx')
        with self.send_mail():
            self.commit(update)
        ticket.refresh_from_db()
        self.assertEqual((ticket.portal_ticket_id, ticket.site_name), (portal_id, 'Updated Site'))
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketNotification.objects.filter(ticket=ticket).count(), 2)

        closed = self.preview([ticket_row(status='Closed', email='', site_name='Closed Site')], name='close.xlsx')
        self.commit(closed)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'Closed')
        self.assertEqual(ticket.closure_source, 'excel_import')
        self.assertEqual(TicketNotification.objects.filter(ticket=ticket).count(), 2)

        reopened = self.preview([ticket_row(email='reopen@example.com')], name='reopen.xlsx')
        with self.send_mail():
            self.commit(reopened)
        ticket.refresh_from_db()
        self.assertEqual((ticket.portal_ticket_id, ticket.status), (portal_id, 'Open'))
        self.assertEqual(TicketNotification.objects.filter(ticket=ticket).count(), 3)
        self.assertEqual(TicketEvent.objects.filter(ticket=ticket).count(), 7)

    def test_closed_new_rows_are_skipped_and_duplicate_rows_are_invalid(self):
        closed = self.preview([ticket_row(status='Closed', email='')])
        self.commit(closed)
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertEqual(closed.counts['closed_rows_skipped'], 1)

        duplicates = self.preview([ticket_row(), ticket_row(serial='2')], name='duplicates.xlsx')
        self.assertEqual(duplicates.counts['invalid_rows'], 2)
        with self.assertRaises(importer.ImportConflict):
            self.commit(duplicates)
        committed = self.commit(duplicates, accept_invalid=True)
        self.assertEqual(committed.counts['new_tickets'], 0)
        self.assertEqual(Ticket.objects.count(), 0)

    def test_exact_workbook_reimport_requires_confirmation_and_commit_is_idempotent(self):
        contents = workbook([ticket_row()])
        batch = importer.preview(contents, 'tickets.xlsx', self.user)
        with self.send_mail():
            first = self.commit(batch)
            duplicate = importer.preview(contents, 'tickets-again.xlsx', self.user)
            with self.assertRaises(importer.ImportConflict):
                self.commit(duplicate)
            confirmed = self.commit(duplicate, confirm_duplicate=True)
            repeated = self.commit(duplicate, confirm_duplicate=True)
        self.assertEqual(first.counts['new_tickets'], 1)
        self.assertEqual(confirmed.counts['existing_tickets_updated'], 1)
        self.assertEqual(repeated.pk, confirmed.pk)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketNotification.objects.count(), 2)

    def test_upload_permission_is_circle_scoped_and_uploaders_can_download_template(self):
        role = Role.objects.create(name='Ticket uploader')
        RolePermission.objects.create(role=role, module='ticket_management', action='upload')
        uploader = portal_user('ticket-uploader', role=None)
        AccessAssignment.objects.create(user=uploader, role=role,
                                        project=Project.objects.get(key='4G Saturation'),
                                        project_circle=ProjectCircle.objects.get(project__key='4G Saturation', circle__code='MP'))
        self.client.force_login(uploader)
        self.assertEqual(self.client.get(reverse('ticket-options')).status_code, 403)
        self.assertEqual(self.client.get(reverse('ticket-template')).status_code, 200)

        unassigned = portal_user('ticket-unassigned', role='ci')
        self.client.force_login(unassigned)
        self.assertEqual(self.client.get(reverse('ticket-options')).status_code, 403)

    def test_manual_close_reopen_requires_reasons_and_records_transitions(self):
        batch = self.preview([ticket_row()])
        with self.send_mail():
            self.commit(batch)
        ticket = Ticket.objects.get()

        missing_close_reason = self.client.post(reverse('ticket-close', args=[ticket.pk]), {}, content_type='application/json')
        self.assertEqual(missing_close_reason.status_code, 400)
        closed = self.client.post(reverse('ticket-close', args=[ticket.pk]), {'remarks': 'Field team confirmed restoration.'},
                                  content_type='application/json')
        self.assertEqual(closed.status_code, 200, closed.content)
        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.closure_source, ticket.closure_remarks), ('Closed', 'manual', 'Field team confirmed restoration.'))

        missing_reopen_reason = self.client.post(reverse('ticket-reopen', args=[ticket.pk]), {}, content_type='application/json')
        self.assertEqual(missing_reopen_reason.status_code, 400)
        with self.send_mail():
            reopened = self.client.post(reverse('ticket-reopen', args=[ticket.pk]), {'reason': 'Further repair required.'},
                                        content_type='application/json')
        self.assertEqual(reopened.status_code, 200, reopened.content)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'Open')
        self.assertEqual(TicketNotification.objects.filter(ticket=ticket).count(), 2)
        self.assertEqual(list(ticket.events.values_list('action', flat=True)), [
            'created', 'notification_accepted', 'closed_manually', 'reopened_manually', 'notification_accepted',
        ])


# --- Technician notifications, authorized closure and the Open-by-default ticket table --------------------------------

from contextlib import nullcontext  # noqa: E402
from datetime import date, datetime, timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402
from django.urls import get_resolver  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.tickets import email_content  # noqa: E402
from apps.tickets.models import TicketStatus  # noqa: E402

FORBIDDEN_IN_EMAIL = ('http://', 'https://', 'href', '<a ', '/tickets/', '/api/', 'password', 'login', 'log in', 'sign in',
                      'sign-in', 'token', 'session', 'username', 'credential', 'reset', 'close ticket', 'click')


class TicketFixtureMixin:
    def setUp(self):
        self.admin = portal_user('ticket-admin', 'admin')
        self.client.force_login(self.admin)
        self.project, _ = Project.objects.get_or_create(key='4G Saturation', defaults={'code': '4G', 'name': '4G Saturation'})
        self.mp, _ = Circle.objects.get_or_create(code='MP', defaults={'name': 'Madhya Pradesh'})
        self.mp_pc, _ = ProjectCircle.objects.get_or_create(project=self.project, circle=self.mp)
        self.site = make_site('MP-TST-001', technology=self.project.key, circle='MP', site_name='Test Site')

    def import_rows(self, rows, *, mail=None):
        batch = importer.preview(workbook(rows), 'tickets.xlsx', self.admin)
        with (mail or successful_mail()):
            return importer.commit(batch.pk, self.admin)

    def scoped_user(self, username, actions, *, email=''):
        """A portal user holding only ``actions`` of Ticket Management on MP (no system role)."""
        role = Role.objects.create(name=f'{username} role')
        for action in actions:
            RolePermission.objects.create(role=role, module='ticket_management', action=action)
        user = portal_user(username, role=None)
        if email:
            user.email = email
            user.save(update_fields=['email'])
        AccessAssignment.objects.create(user=user, role=role, project=self.project, project_circle=self.mp_pc)
        return user


class TechnicianNotificationTests(TicketFixtureMixin, TestCase):
    def test_each_row_creates_one_ticket_and_one_email_to_its_own_recipient_without_user_accounts(self):
        make_site('MP-TST-002', technology=self.project.key, circle='MP', site_name='Second Site')
        second = ticket_row(serial='2', email='second.tech@example.com', site_name='Second Site')
        second[3] = 'MP-TST-002'
        users_before = get_user_model().objects.count()
        with patch('apps.tickets.services.engine.active_account', return_value=object()):
            with patch('apps.tickets.services.mailer.send', return_value='250 accepted') as send:
                batch = importer.preview(workbook([ticket_row(email='first.tech@example.com'), second]), 'two.xlsx', self.admin)
                committed = importer.commit(batch.pk, self.admin)

        self.assertEqual(committed.counts['new_tickets'], 2)
        self.assertEqual(Ticket.objects.count(), 2)
        self.assertEqual(len({t.portal_ticket_id for t in Ticket.objects.all()}), 2)
        self.assertEqual(sorted(call.args[1].to[0] for call in send.call_args_list), ['first.tech@example.com', 'second.tech@example.com'])
        for call in send.call_args_list:
            self.assertEqual(len(call.args[1].to), 1)
            self.assertEqual((call.args[1].cc, call.args[1].bcc), ([], []))
        for ticket in Ticket.objects.all():
            notification = ticket.notifications.get()
            self.assertEqual(notification.recipient, ticket.email_id)
            self.assertIn(ticket.portal_ticket_id, notification.html_body)
        # No portal account is created for, or matched to, a technician.
        self.assertEqual(get_user_model().objects.count(), users_before)
        recipients = ['first.tech@example.com', 'second.tech@example.com']
        self.assertFalse(get_user_model().objects.filter(email__in=recipients).exists())
        self.assertFalse(get_user_model().objects.filter(username__in=recipients).exists())

    def test_email_contains_the_ticket_and_outage_details(self):
        self.import_rows([ticket_row()])
        ticket = Ticket.objects.get()
        notification = ticket.notifications.get()
        local = timezone.localtime(ticket.actual_down_time).strftime('%d %b %Y, %H:%M')
        for expected in (ticket.portal_ticket_id, '04 Nov 2026', 'MP', 'MP-TST-001', 'Test Site', 'Bhopal', 'Bhopal BA', local,
                         '150', '2.5', 'Vendor A', 'OFC Cut', 'Fiber cut near highway', 'dispatch@example.com',
                         'informational notification', 'authorized BSNL team'):
            self.assertIn(expected, notification.html_body)
            self.assertIn(expected, notification.text_body)
        self.assertIn(ticket.portal_ticket_id, notification.subject)
        self.assertIn('Test Site', notification.subject)
        self.assertEqual(email_content.detail_rows(ticket)[0], ('Ticket ID', ticket.portal_ticket_id))

    def test_email_has_no_portal_access_credentials_links_or_closure_actions(self):
        self.import_rows([ticket_row()])
        notification = TicketNotification.objects.get()
        for body in (notification.html_body, notification.text_body, notification.subject):
            lowered = body.lower()
            for forbidden in FORBIDDEN_IN_EMAIL:
                self.assertNotIn(forbidden, lowered)
        self.assertNotIn('<form', notification.html_body.lower())
        self.assertNotIn('<button', notification.html_body.lower())

    def test_missing_optional_fields_are_omitted_and_values_are_escaped(self):
        ticket = Ticket(portal_ticket_id='OFC-2026-09999', outage_date=date(2026, 11, 4), project='4G Saturation', circle='MP',
                        site_id='MP-TST-009', site_key='MP-TST-009', site_name='', email_id='tech@example.com',
                        actual_down_time=timezone.make_aware(datetime(2026, 11, 4, 2, 15)), detail_rca='<script>alert(1)</script>',
                        outage_minutes=Decimal('0.00'))
        for kind in ('created', 'updated', 'reopened'):
            subject, text, html = email_content.render(ticket, kind)
            self.assertIn('OFC-2026-09999', subject)
            self.assertIn('MP-TST-009', subject)  # Site ID stands in for a missing Site Name
            for absent in ('Site Name', '>OA<', 'Restoration Time', 'Reporting Time to Partner', 'MTTR', 'Vendor Name', 'Outage Bucket'):
                self.assertNotIn(absent, html)
            self.assertIn('Outage Minutes', html)  # zero is a value, not a missing one
            self.assertNotIn('<script>', html)
            self.assertIn('&lt;script&gt;', html)
            self.assertIn('<script>alert(1)</script>', text)  # plain text is not HTML

    def test_failed_email_keeps_ticket_and_retry_reuses_the_same_notification(self):
        with patch('apps.tickets.services.engine.active_account', return_value=object()):
            with patch('apps.tickets.services.mailer.send', side_effect=MailError('SMTP unavailable')):
                self.import_rows([ticket_row()], mail=nullcontext())
        ticket = Ticket.objects.get()
        notification = TicketNotification.objects.get()
        self.assertEqual((ticket.status, notification.status, notification.sent_at), ('Open', 'failed', None))

        with successful_mail():
            retried = self.client.post(reverse('ticket-notification-retry', args=[notification.pk]))
            again = self.client.post(reverse('ticket-notification-retry', args=[notification.pk]))
        self.assertEqual(retried.status_code, 200, retried.content)
        self.assertEqual(again.status_code, 409)
        notification.refresh_from_db()
        self.assertEqual((notification.status, notification.attempts), ('accepted', 2))
        self.assertIsNotNone(notification.sent_at)
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(TicketNotification.objects.count(), 1)
        self.assertEqual(notification.attempt_log.count(), 2)


class TicketClosureSecurityTests(TicketFixtureMixin, TestCase):
    TECH_EMAIL = 'field.tech@example.com'

    def setUp(self):
        super().setUp()
        self.import_rows([ticket_row(email=self.TECH_EMAIL)])
        self.ticket = Ticket.objects.get()
        self.url = reverse('ticket-close', args=[self.ticket.pk])

    def close(self, payload=None):
        return self.client.post(self.url, payload or {'remarks': 'Restored by field team.'}, content_type='application/json')

    def assert_still_open(self):
        self.ticket.refresh_from_db()
        self.assertEqual((self.ticket.status, self.ticket.closed_by_id, self.ticket.closed_at), ('Open', None, None))

    def test_unauthenticated_request_cannot_close_even_with_the_technician_email(self):
        self.client.logout()
        for payload in ({'remarks': 'Done'}, {'remarks': 'Done', 'email': self.TECH_EMAIL, 'email_id': self.TECH_EMAIL}):
            self.assertIn(self.close(payload).status_code, (401, 403))
        self.assertIn(self.client.get(f'{self.url}?email={self.TECH_EMAIL}').status_code, (401, 403, 405))
        self.assert_still_open()

    def test_a_portal_user_whose_email_matches_the_recipient_gets_no_closure_right(self):
        technician = portal_user('field-tech', role=None)
        technician.email = self.TECH_EMAIL
        technician.save(update_fields=['email'])
        self.client.force_login(technician)
        self.assertIn(self.close({'remarks': 'Done', 'email': self.TECH_EMAIL}).status_code, (403, 404))
        self.assert_still_open()

        viewer = self.scoped_user('tech-viewer', ['view'], email=self.TECH_EMAIL)
        self.client.force_login(viewer)
        self.assertEqual(self.close().status_code, 403)
        self.assert_still_open()

    def test_authenticated_user_without_close_permission_is_refused_and_sees_no_close_action(self):
        viewer = self.scoped_user('ticket-viewer', ['view', 'retry'])
        self.client.force_login(viewer)
        rows = self.client.get(reverse('ticket-records')).json()['tickets']
        self.assertEqual([(r['id'], r['can_close']) for r in rows], [(self.ticket.pk, False)])
        self.assertFalse(self.client.get(reverse('ticket-detail', args=[self.ticket.pk])).json()['permissions']['close'])
        self.assertEqual(self.close().status_code, 403)
        self.assert_still_open()

    def test_authorized_user_closes_with_remarks_and_identity_time_and_counts_are_recorded(self):
        closer = self.scoped_user('ticket-closer', ['view', 'close'])
        self.client.force_login(closer)
        self.assertTrue(self.client.get(reverse('ticket-records')).json()['tickets'][0]['can_close'])
        self.assertEqual(self.close({'remarks': '   '}).status_code, 400)
        self.assert_still_open()

        before = timezone.now()
        response = self.close({'remarks': '  Splice repaired at chamber 4.  '})
        self.assertEqual(response.status_code, 200, response.content)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, TicketStatus.CLOSED)
        self.assertEqual(self.ticket.closed_by, closer)
        self.assertEqual(self.ticket.closure_remarks, 'Splice repaired at chamber 4.')
        self.assertEqual(self.ticket.closure_source, 'manual')
        self.assertGreaterEqual(self.ticket.closed_at, before)
        event = self.ticket.events.get(action='closed_manually')
        self.assertEqual((event.actor, event.status_before, event.status_after), (closer, 'Open', 'Closed'))
        self.assertEqual(self.close().status_code, 409)  # already closed

        kpis = self.client.get(reverse('ticket-dashboard')).json()['kpis']
        self.assertEqual((kpis['total'], kpis['open'], kpis['closed']), (1, 0, 1))
        self.assertEqual(self.client.get(reverse('ticket-records')).json()['total'], 0)
        closed = self.client.get(reverse('ticket-records'), {'status': 'Closed'}).json()
        self.assertEqual([(r['portal_ticket_id'], r['can_close']) for r in closed['tickets']], [(self.ticket.portal_ticket_id, False)])

    def test_closure_has_no_unauthenticated_or_email_route(self):
        def walk(patterns, prefix=''):
            for p in patterns:
                if hasattr(p, 'url_patterns'):
                    yield from walk(p.url_patterns, prefix + str(p.pattern))
                else:
                    yield prefix + str(p.pattern)
        routes = list(walk(get_resolver().url_patterns))
        self.assertTrue(any(r.endswith('<int:ticket_id>/close/') for r in routes))
        self.assertFalse(any('ticket' in r.lower() and ('email' in r.lower() or 'token' in r.lower()) for r in routes))
        self.client.logout()
        for name in ('ticket-records', 'ticket-dashboard'):
            self.assertIn(self.client.get(reverse(name)).status_code, (401, 403))


class TicketTableFilterTests(TicketFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.kl, _ = Circle.objects.get_or_create(code='KL', defaults={'name': 'Kerala'})
        ProjectCircle.objects.get_or_create(project=self.project, circle=self.kl)
        self.serial = 0

    def make(self, *, status='Open', circle='MP', vendor='Vendor A', site_name='Alpha Site', day=4):
        self.serial += 1
        now = timezone.now()
        down = timezone.make_aware(datetime(2026, 11, day, 2, 0)) + timedelta(minutes=self.serial)
        return Ticket.objects.create(
            portal_ticket_id=f'OFC-2026-{self.serial:05d}', outage_date=date(2026, 11, day), project=self.project.key, circle=circle,
            site_id=f'{circle}-S-{self.serial:03d}', site_key=f'{circle}-S-{self.serial:03d}', site_name=site_name,
            actual_down_time=down, vendor_name=vendor, status=status, email_id='tech@example.com', last_uploaded_at=now,
            closed_at=now if status == 'Closed' else None)

    def records(self, **params):
        response = self.client.get(reverse('ticket-records'), params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_default_is_open_and_closed_and_all_are_selectable(self):
        opened = [self.make() for _ in range(3)]
        closed = [self.make(status='Closed') for _ in range(2)]
        default = self.records()
        self.assertEqual(default['status'], 'Open')
        self.assertEqual({t['id'] for t in default['tickets']}, {t.pk for t in opened})
        self.assertEqual(default['total'], 3)
        self.assertEqual(self.records(status='')['total'], 3)
        only_closed = self.records(status='Closed')
        self.assertEqual({t['id'] for t in only_closed['tickets']}, {t.pk for t in closed})
        self.assertEqual({t['status'] for t in only_closed['tickets']}, {'Closed'})
        both = self.records(status='All')
        self.assertEqual((both['total'], {t['status'] for t in both['tickets']}), (5, {'Open', 'Closed'}))
        self.assertEqual(self.client.get(reverse('ticket-records'), {'status': 'Pending'}).status_code, 400)
        self.assertEqual(Ticket.objects.count(), 5)  # nothing is archived or deleted

    def test_search_circle_vendor_date_and_status_filters_combine(self):
        target = self.make(circle='KL', vendor='Vendor B', site_name='Kochi Hub', day=6)
        self.make(circle='KL', vendor='Vendor B', site_name='Kochi Hub', day=6, status='Closed')  # wrong status
        self.make(circle='MP', vendor='Vendor B', site_name='Kochi Hub', day=6)  # wrong circle
        self.make(circle='KL', vendor='Vendor A', site_name='Kochi Hub', day=6)  # wrong vendor
        self.make(circle='KL', vendor='Vendor B', site_name='Kochi Hub', day=2)  # outside the dates
        self.make(circle='KL', vendor='Vendor B', site_name='Other', day=6)  # search miss
        params = {'q': 'kochi', 'circle': 'KL', 'vendor_name': 'Vendor B', 'date_from': '2026-11-05', 'date_to': '2026-11-07'}
        combined = self.records(**params)
        self.assertEqual(([t['id'] for t in combined['tickets']], combined['total']), ([target.pk], 1))
        self.assertEqual(self.records(**params, status='All')['total'], 2)
        self.assertEqual(self.records(**params, status='Closed')['total'], 1)
        self.assertEqual(self.records(q=target.portal_ticket_id)['total'], 1)
        self.assertEqual(self.records(q=target.site_id.lower())['total'], 1)

    def test_counts_and_pagination_follow_the_filters_and_kpis_stay_overall(self):
        for _ in range(30):
            self.make()
        for _ in range(4):
            self.make(status='Closed', circle='KL')
        first = self.records(page_size=25)
        second = self.records(page_size=25, page=2)
        self.assertEqual((first['total'], first['pages'], len(first['tickets']), len(second['tickets'])), (30, 2, 25, 5))
        self.assertFalse({t['id'] for t in first['tickets']} & {t['id'] for t in second['tickets']})
        closed = self.records(status='Closed', page=1, page_size=25)
        self.assertEqual((closed['total'], closed['pages'], len(closed['tickets'])), (4, 1, 4))
        everything = self.records(status='All', page_size=100)
        self.assertEqual((everything['total'], len(everything['tickets'])), (34, 34))
        # A table filter changes the table count only; the dashboard KPIs (requested without filters) stay overall.
        for params in ({'status': 'Closed'}, {'status': 'Open', 'circle': 'KL'}, {'status': 'All', 'q': 'nothing'}):
            self.records(**params)
            kpis = self.client.get(reverse('ticket-dashboard')).json()['kpis']
            self.assertEqual((kpis['total'], kpis['open'], kpis['closed']), (34, 30, 4))

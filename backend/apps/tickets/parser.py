from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from zipfile import BadZipFile

from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
from openpyxl.utils.exceptions import InvalidFileException


HEADERS = (
    'Sr.No.', 'Date', 'Circle', 'Site ID', 'Site Name', 'OA', 'BA', 'Actual Down Time',
    'Reporting Time to Partner', 'Restoration Time', 'Outage Min.', 'MTTR (Hrs.)', 'Vendor Name',
    'Outage Bucket', 'Detail RCA', 'TT Status', 'Email ID',
)
MAX_ROWS = 20_000
SAMPLE_VALUES = (
    '1', '2026-11-04', 'KERALA', 'KER-TVM-1029', 'Trivandrum Central', 'TVM', 'TVM-BA',
    '2026-11-04 02:15:00', '2026-11-04 02:30:00', '2026-11-04 04:45:00', '150',
    '02:30:00', 'L&T', 'OFC Cut', 'OFC cut during NH road expansion work near bypass', 'Closed',
    'noc-lead@bsnl.in',
)


class WorkbookError(ValueError):
    pass


def _header(value) -> str:
    return ' '.join(str(value or '').split())


def _cell_text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.isoformat(sep=' ')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _excel_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = from_excel(value)
        if isinstance(converted, datetime):
            return converted.date()
        raise ValueError
    text = _cell_text(value)
    try:
        return date.fromisoformat(text)
    except ValueError:
        for fmt in ('%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y'):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    raise ValueError


def _excel_datetime(value, day: date | None = None) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, time):
        if day is None:
            raise ValueError
        return datetime.combine(day, value)
    if isinstance(value, timedelta):
        if day is None:
            raise ValueError
        return datetime.combine(day, time.min) + value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = from_excel(value)
        if isinstance(converted, datetime):
            return converted
        if isinstance(converted, time) and day is not None:
            return datetime.combine(day, converted)
        raise ValueError
    text = _cell_text(value)
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        for fmt in ('%d/%m/%Y %H:%M:%S', '%d-%m-%Y %H:%M:%S', '%d-%m-%Y%H:%M:%S',
                    '%d/%m/%Y %H:%M', '%d-%m-%Y %H:%M'):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    if day is not None:
        try:
            return datetime.combine(day, time.fromisoformat(text))
        except ValueError:
            pass
    raise ValueError


def _decimal(value, *, duration: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError
    if isinstance(value, timedelta):
        number = Decimal(str(value.total_seconds())) / Decimal(3600 if duration else 60)
    elif isinstance(value, time):
        number = (Decimal(value.hour * 3600 + value.minute * 60 + value.second) +
                  Decimal(value.microsecond) / Decimal(1_000_000)) / Decimal(3600 if duration else 60)
    else:
        text = _cell_text(value)
        if duration and ':' in text:
            parts = text.split(':')
            if len(parts) not in (2, 3):
                raise ValueError
            hours = Decimal(parts[0])
            minutes = Decimal(parts[1])
            seconds = Decimal(parts[2]) if len(parts) == 3 else Decimal(0)
            if hours != hours.to_integral_value() or minutes != minutes.to_integral_value() or minutes >= 60 or seconds >= 60:
                raise ValueError
            number = hours + minutes / Decimal(60) + seconds / Decimal(3600)
        else:
            number = Decimal(text)
    if not number.is_finite() or number < 0:
        raise ValueError
    return number


def _elapsed_minutes(start_value, end_value, day: date | None) -> Decimal | None:
    if start_value in (None, '') or end_value in (None, ''):
        return None
    try:
        elapsed = _excel_datetime(end_value, day) - _excel_datetime(start_value, day)
    except (ValueError, TypeError, OverflowError):
        return None
    if elapsed < timedelta(0):
        return None
    microseconds = (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds
    return Decimal(microseconds) / Decimal(60_000_000)


def _normalize_computed_precision(value, expected: Decimal | None, places: int,
                                  tolerance: Decimal):
    if expected is None or value in (None, ''):
        return value
    try:
        number = _decimal(value)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return value
    quantum = Decimal(1).scaleb(-places)
    rounded = number.quantize(quantum, rounding=ROUND_HALF_UP)
    expected_rounded = expected.quantize(quantum, rounding=ROUND_HALF_UP)
    if number != rounded and rounded == expected_rounded and abs(number - expected) <= tolerance:
        return expected_rounded
    return value


def _sample_signature(values: list[str]) -> bool:
    return tuple(values) == SAMPLE_VALUES


def parse_workbook(contents: bytes) -> dict:
    formula_workbook = None
    value_workbook = None
    try:
        formula_workbook = load_workbook(BytesIO(contents), data_only=False, read_only=True)
        value_workbook = load_workbook(BytesIO(contents), data_only=True, read_only=True)
    except (InvalidFileException, BadZipFile, OSError, ValueError) as exc:
        if formula_workbook is not None:
            formula_workbook.close()
        if value_workbook is not None:
            value_workbook.close()
        raise WorkbookError('The file is not a readable Excel workbook.') from exc

    try:
        if 'Ticket_Upload' not in formula_workbook.sheetnames:
            raise WorkbookError('The required "Ticket_Upload" worksheet is missing.')
        sheet = formula_workbook['Ticket_Upload']
        value_sheet = value_workbook['Ticket_Upload']
        header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
        normalized = [_header(value) for value in header_row]
        duplicates = {name for name in normalized if name in HEADERS and normalized.count(name) > 1}
        if duplicates:
            raise WorkbookError('Duplicate standard column header: ' + ', '.join(sorted(duplicates)) + '.')
        if len(normalized) < len(HEADERS):
            raise WorkbookError(f'The Ticket_Upload worksheet must contain all {len(HEADERS)} standard columns in order.')
        actual = normalized[:len(HEADERS)]
        if actual != list(HEADERS):
            for index, expected in enumerate(HEADERS):
                found = actual[index] if index < len(actual) else ''
                if found != expected:
                    if expected in actual:
                        raise WorkbookError(f'Column order is invalid at position {index + 1}: expected "{expected}", found "{found}".')
                    raise WorkbookError(f'Missing or renamed standard column at position {index + 1}: expected "{expected}", found "{found or "(blank)"}".')
        if any(normalized[len(HEADERS):]):
            raise WorkbookError('The Ticket_Upload worksheet cannot contain additional data columns after the 17 standard columns.')

        rows = []
        blank_rows = 0
        sample_rows = 0
        value_rows = value_sheet.iter_rows(min_row=2, max_col=len(HEADERS))
        for excel_row, (cell_row, cached_row) in enumerate(
            zip(sheet.iter_rows(min_row=2, max_col=len(HEADERS)), value_rows), start=2
        ):
            if excel_row > MAX_ROWS + 1:
                raise WorkbookError(f'The workbook exceeds the {MAX_ROWS:,}-row limit.')
            cells = tuple(cell.value for cell in cell_row)
            cached_cells = tuple(cell.value for cell in cached_row)
            formulas = [index for index, cell in enumerate(cell_row) if cell.data_type == 'f']
            if not any(value is not None and _cell_text(value) for value in cells):
                blank_rows += 1
                continue
            effective_cells = list(cells)
            numeric_formula_indices = (10, 11)
            missing_formula_results = set()
            for index in numeric_formula_indices:
                if index in formulas:
                    if cached_cells[index] is None:
                        effective_cells[index] = None
                        missing_formula_results.add(index)
                    else:
                        effective_cells[index] = cached_cells[index]
            raw = [_cell_text(value) for value in effective_cells]
            row = {'excel_row': excel_row, 'source_values': dict(zip(HEADERS, raw)), 'errors': []}
            if _sample_signature(raw):
                sample_rows += 1
                row['outcome'] = 'sample_skipped'
                rows.append(row)
                continue

            values = {}

            def error(field: str, message: str) -> None:
                row['errors'].append({'field': field, 'message': message})

            for index in formulas:
                if index in numeric_formula_indices:
                    if index in missing_formula_results:
                        error(HEADERS[index], 'Formula result is unavailable. Open the workbook in Excel, recalculate formulas, save the file, and upload again.')
                else:
                    error(HEADERS[index], 'Formula cells are not supported; replace the formula with a value.')

            values['source_serial'] = raw[0]
            if len(values['source_serial']) > 50:
                error('Sr.No.', 'This value must be 50 characters or fewer.')
            try:
                values['outage_date'] = _excel_date(cells[1]).isoformat() if cells[1] not in (None, '') else ''
                if not values['outage_date']:
                    error('Date', 'Enter the outage date.')
            except (ValueError, TypeError, OverflowError):
                values['outage_date'] = ''
                error('Date', 'Enter a valid date.')

            values['circle_raw'] = raw[2].strip()
            if not values['circle_raw']:
                error('Circle', 'Enter the circle.')
            elif len(values['circle_raw']) > 60:
                error('Circle', 'This value must be 60 characters or fewer.')
            values['site_id'] = raw[3].strip()
            if not values['site_id']:
                error('Site ID', 'Enter the Site ID.')
            elif len(values['site_id']) > 60:
                error('Site ID', 'This value must be 60 characters or fewer.')
            values['site_name'] = raw[4]
            values['oa'] = raw[5]
            values['ba'] = raw[6]
            for field, value, limit in (('Site Name', values['site_name'], 200), ('OA', values['oa'], 100), ('BA', values['ba'], 100)):
                if len(value) > limit:
                    error(field, f'This value must be {limit} characters or fewer.')

            try:
                outage_day = date.fromisoformat(values['outage_date']) if values['outage_date'] else None
                values['actual_down_time'] = _excel_datetime(cells[7], outage_day).replace(microsecond=0).isoformat(sep=' ') if cells[7] not in (None, '') else ''
                if not values['actual_down_time']:
                    error('Actual Down Time', 'Enter the outage start time; it is required to match the outage.')
            except (ValueError, TypeError, OverflowError):
                values['actual_down_time'] = ''
                error('Actual Down Time', 'Enter a valid date and time.')

            for index, field in ((8, 'reporting_time_to_partner'), (9, 'restoration_time')):
                try:
                    values[field] = _excel_datetime(cells[index], outage_day).replace(microsecond=0).isoformat(sep=' ') if cells[index] not in (None, '') else ''
                except (ValueError, TypeError, OverflowError):
                    values[field] = ''
                    error(HEADERS[index], 'Enter a valid date and time, or leave it blank.')

            expected_outage_minutes = _elapsed_minutes(cells[7], cells[9], outage_day)
            normalized_outage = _normalize_computed_precision(
                effective_cells[10], expected_outage_minutes, 2, Decimal('0.00001')
            )
            try:
                raw_outage_for_mttr = _decimal(effective_cells[10])
                expected_mttr = raw_outage_for_mttr / Decimal(60)
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                expected_mttr = None
            normalized_mttr = _normalize_computed_precision(
                effective_cells[11], expected_mttr, 4, Decimal('0.000000001')
            )
            raw[10] = _cell_text(normalized_outage)
            raw[11] = _cell_text(normalized_mttr)
            row['source_values']['Outage Min.'] = raw[10]
            row['source_values']['MTTR (Hrs.)'] = raw[11]

            try:
                outage_minutes = _decimal(normalized_outage) if 10 not in missing_formula_results and normalized_outage not in (None, '') else None
                if outage_minutes is not None and (outage_minutes >= Decimal('100000000') or outage_minutes != outage_minutes.quantize(Decimal('0.01'))):
                    raise ValueError
                values['outage_minutes'] = str(outage_minutes) if outage_minutes is not None else ''
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                values['outage_minutes'] = ''
                error('Outage Min.', 'Enter a non-negative number with at most two decimal places, or leave it blank.')
            try:
                mttr_hours = _decimal(normalized_mttr, duration=True) if 11 not in missing_formula_results and normalized_mttr not in (None, '') else None
                if mttr_hours is not None and (mttr_hours >= Decimal('1000000') or mttr_hours != mttr_hours.quantize(Decimal('0.0001'))):
                    raise ValueError
                values['mttr_hours'] = str(mttr_hours) if mttr_hours is not None else ''
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                values['mttr_hours'] = ''
                error('MTTR (Hrs.)', 'Enter a non-negative duration with at most four decimal places, or leave it blank.')

            values['vendor_name'] = raw[12]
            values['outage_bucket'] = raw[13]
            values['detail_rca'] = raw[14]
            for field, value, limit in (('Vendor Name', values['vendor_name'], 200), ('Outage Bucket', values['outage_bucket'], 120)):
                if len(value) > limit:
                    error(field, f'This value must be {limit} characters or fewer.')
            status_value = raw[15].strip().casefold()
            values['status'] = {'open': 'Open', 'closed': 'Closed'}.get(status_value, '')
            if not values['status']:
                error('TT Status', 'Choose Open or Closed.')
            values['email_id'] = raw[16].strip()
            if len(values['email_id']) > 254:
                error('Email ID', 'This value must be 254 characters or fewer.')
            if values['email_id']:
                try:
                    validate_email(values['email_id'])
                except DjangoValidationError:
                    error('Email ID', 'Enter a valid email address.')
            if values['status'] == 'Open' and not values['email_id']:
                error('Email ID', 'An email address is required for an Open ticket.')

            row['values'] = values
            row['outcome'] = 'invalid' if row['errors'] else 'valid'
            rows.append(row)

        if not rows:
            raise WorkbookError('The workbook contains no ticket rows.')

        seen: dict[tuple[str, str, str], list[dict]] = {}
        for row in rows:
            if row['outcome'] != 'valid':
                continue
            values = row['values']
            key = (values['site_id'].upper(), values['outage_date'], values['actual_down_time'])
            seen.setdefault(key, []).append(row)
        for matches in seen.values():
            if len(matches) > 1:
                for row in matches:
                    row['errors'].append({'field': 'Site ID / Date / Actual Down Time',
                                          'message': f'Duplicate outage key appears in Excel rows {", ".join(str(item["excel_row"]) for item in matches)}; resolve the duplicate rows before importing.'})
                    row['outcome'] = 'invalid'

        return {
            'rows': rows,
            'counts': {
                'rows_read': sum(1 for row in rows if row['outcome'] != 'sample_skipped'),
                'blank_rows': blank_rows,
                'sample_rows_skipped': sample_rows,
                'invalid_rows': sum(1 for row in rows if row['outcome'] == 'invalid'),
                'valid_rows': sum(1 for row in rows if row['outcome'] == 'valid'),
            },
        }
    finally:
        formula_workbook.close()
        value_workbook.close()

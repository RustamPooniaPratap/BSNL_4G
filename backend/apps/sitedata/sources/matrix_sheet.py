"""Layout of the Consolidation (Escalation) Matrix "Raw Data" sheet and its cell readers. Parsing only; the import into
the data layer is sitedata.matrix."""
from __future__ import annotations

import re
from datetime import date, datetime

from .uptime_report import site_key  # noqa: F401 (the matching key of a site ID, shared by the importers)

SHEET = 'Raw Data'
KEY_HEADER = 'BSNL Site ID'

# Normalised header -> field. "Contact" appears several times; it belongs to the person named just before it.
COLUMNS = {
    'entity': 'entity_raw', 'site type': 'site_type', 'circle name': 'circle_raw', 'bsnl site id': 'site_id',
    'site name/village name': 'site_name', 'village code': 'village_code', 'ba': 'ba', 'oa': 'oa',
    'district': 'district', 'sub-district': 'sub_district',
    'site commissioning /hoto date': 'commissioning_date', 'site commissioning /hoto status': 'commissioning_status',
    'o&m status': 'om_status', 'o&m start date': 'om_start_date', 'eb status': 'eb_status', 'dg status': 'dg_status',
    'case type': 'case_type', 'site on air status': 'on_air_status', 'site on air date': 'on_air_date',
    'ie emp code': 'ie_emp_code', 'ie name': 'ie_name', 'ie contact': 'ie_contact',
    'ci emp code': 'ci_emp_code', 'ci name': 'ci_name', 'ci contact': 'ci_contact',
    'il emp id': 'il_emp_code', 'il name': 'il_name',
    'o&m manager emp code': 'om_manager_emp_code', 'o&m manager name': 'om_manager_name',
    'o&m manager contact': 'om_manager_contact', 'cbh name': 'cbh_name',
    'ct status': 'ct_status', 'ct name': 'ct_name', 'ct contact': 'ct_contact', 'site address': 'site_address',
    'lattitude': 'latitude', 'latitude': 'latitude', 'longitude': 'longitude',
    'rigger emp id': 'rigger_emp_code', 'rigger name': 'rigger_name', 'other remarks (if any)': 'remarks',
    'ccu/smps make': 'smps_make', 'bts site id_b1(21mhz)': 'bts_id_b1', 'bts site id_b28(7mhz)': 'bts_id_b28',
    'master bts id': 'master_bts_id',
}
CONTACT_AFTER = {'il_name': 'il_contact', 'cbh_name': 'cbh_contact', 'rigger_name': 'rigger_contact'}
# Serial number and the sheet's own formatting helpers ("Mr. _<name>_MB:-<number>"): not stored.
SKIPPED = {'sl', '@', 'combo'}
DATES = {'commissioning_date': 'commissioning_raw', 'om_start_date': 'om_start_raw', 'on_air_date': 'on_air_raw'}
EMPTY = {'', '-', 'na', 'n/a', 'tbd', 'vacant'}


def _header(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (datetime, date)):
        return value.strftime('%Y-%m-%d')
    return re.sub(r'\s+', ' ', str(value)).strip()


def _date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _coordinate(value) -> float | None:
    """A coordinate, or None for blanks, text and 0 (the source's placeholder, never a real position here)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number else None


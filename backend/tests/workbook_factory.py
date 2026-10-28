"""Build small synthetic Master workbooks that mirror the real Up-Time Report layout.

Layout reproduced from the Oct'26 workbook: a totals row, a header row, site
columns, an "O&M Start - Oct-26" flag, an "Oct-26 Outage Min." total, the daily
outage block, weekly sums, then a second block with the same date labels
holding derived up-time (which the loader must ignore).
"""
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

OCTOBER = [date(2026, 10, day) for day in range(1, 32)]
SEPTEMBER = [date(2026, 9, day) for day in range(1, 31)]

# (project, circle, btsIpId, site name, on_air, om_start, daily outage minutes for 1-3 Oct)
DEFAULT_SITES = [
    ('4G Satu.', 'MP', 'UVMP001', 'Alpha', 'Yes', 'Yes', [0, 144, 1440]),
    ('4G Satu.', 'MP', 'UVMP002', 'Bravo', 'Yes', None, [72, 0, 0]),
    ('4G Satu.', 'MP', 'UVMP003', 'Charlie', None, None, [1440, 1440, 1440]),
    ('4G Satu.', 'RJ', 'UVRJ001', 'Delta', 'Yes', 'Yes', [0, 0, 0]),
    ('LWE', 'Madhya Pradesh', 'LWEMP01', 'Echo', 'Yes', 'Yes', [288, 0, 0]),
    ('LWE', 'Odisha', 'LWEOD01', 'Foxtrot', 'Yes', 'Yes', [0, 720, None]),
    ('LWE', 'BH', 'LWEBH01', 'Golf', 0, 'Yes', [0, 0, 14.4]),
]


def build_rows(sites=None, *, include_om_start=True, extra_columns=None, monthly=None, september=None,
               september_as_uptime=False):
    """``monthly`` maps a header such as 'Sep-26 Outage Min.' to one value per site.

    ``september`` adds daily outage for 1-30 Sep (one list per site) BEFORE the October block,
    plus a derived Sep uptime block at the end, as a workbook with both months would.
    ``september_as_uptime`` writes the Sep values as uptime fractions instead of minutes.
    """
    monthly = monthly or {}
    sites = DEFAULT_SITES if sites is None else sites
    headers = ['Project', 'Circle', 'btsIpId', 'Site name', 'OA', 'BA', 'On-Air', 'EB']
    if include_om_start:
        headers.append('O&M Start - Oct-26')
    headers += ['IE Name', 'CI Name', 'Oct-26 Outage Min.', 'Oct-26 UpTime', 'Bucket']
    if september is not None:
        headers += [datetime.combine(d, datetime.min.time()) for d in SEPTEMBER]
    headers += [datetime.combine(d, datetime.min.time()) for d in OCTOBER]
    headers += ['Wk-1', 'Wk-2']
    headers += [datetime.combine(d, datetime.min.time()) for d in OCTOBER]
    headers += list(extra_columns or [])
    headers += list(monthly)
    if september is not None:
        headers += [datetime.combine(d, datetime.min.time()) for d in SEPTEMBER]  # derived Sep uptime (ignored)

    rows = []
    for index, (project, circle, site_id, name, on_air, om_start, outage) in enumerate(sites):
        daily = list(outage) + [None] * (31 - len(outage))
        total = sum(v for v in daily if isinstance(v, (int, float)))
        row = [project, circle, site_id, name, 'OA-1', 'BA-1', on_air, 'EB']
        if include_om_start:
            row.append(om_start)
        row += [f'IE {circle}', 'CI East' if index % 2 == 0 else 'CI West', total, None, None]
        sep = (list(september[index]) + [None] * 30)[:30] if september is not None else []
        to_uptime = lambda v: 1 - v / 1440 if isinstance(v, (int, float)) else None  # noqa: E731
        if september is not None:
            row += [to_uptime(v) for v in sep] if september_as_uptime else sep
        row += daily
        row += [None, None]
        # Derived up-time block: 100% for unreported days, exactly like the workbook.
        row += [1 - (v / 1440 if isinstance(v, (int, float)) else 0) for v in daily]
        row += [None] * len(extra_columns or [])
        row += [values[index] for values in monthly.values()]
        if september is not None:
            row += [to_uptime(v) if v is not None else 1 for v in sep]
        rows.append(row)
    return headers, rows


def write_workbook(path: Path, sites=None, *, sheet_name='Up-Time Report', summary_sheets=None, **kwargs) -> Path:
    """``summary_sheets`` maps a sheet name (e.g. 'Summ') to rows written from cell A1."""
    headers, rows = build_rows(sites, **kwargs)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append([None, 7] + [0] * (len(headers) - 2))  # totals row, as in the real sheet
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    for name, sheet_rows in (summary_sheets or {'Summ': []}).items():
        summary = workbook.create_sheet(name)
        for row in sheet_rows:
            summary.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


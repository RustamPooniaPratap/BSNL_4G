"""Auto Email Reports: the reference ``buildReport`` (D-1 and Weekly, per Circle and All India) on portal data.

Every figure comes from the portal's approved rules in apps.dashboard.metrics (decision 17 Nov 2026), computed per site
with the same primitives the dashboard uses, so a Circle's uptime here equals its uptime on the dashboard:

- population: the On-Air sites of the period, each counted from its effective date (population_eligible / _view);
- uptime % = 100 x (1 - outage minutes / (1440 x site-days reported)), pooled over the sites and reported days;
- SLA target 98.5% (metrics.NSLA_THRESHOLD); "Sites not meeting SLA" = NSLA (nsla_mask);
- USD = sites with outage > 0 on at least one reported day (usd_mask): the portal counts sites, not outage events;
- outage minutes are summed from the underlying daily and RCA durations; hour-based values remain internal for compatibility.

Not reproduced, because the portal holds no outage start / end times: Sites down now, MTTR, longest outage, long-down
sites and repeat offenders. Circles and CIs are ranked by the portal's rule (lowest NSLA share first, then uptime)
instead of the reference score, which needs USD events.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape

import numpy as np

from apps.dashboard import metrics
from apps.dashboard.workbook import MINUTES_PER_DAY

from .common import BUCKETS, Period, d_long, d_short, fmt, rca_rows, report_period, whole_minutes
from .classification import responsibility_label
from .models import Bucket, DistributionRecipient, ReportType

SCOPE = metrics.DEFAULT_SCOPE  # On-Air, the portal's default population
TARGET = metrics.NSLA_THRESHOLD
EXCLUDABLE = (Bucket.CUSTOMER, Bucket.THIRD_PARTY)
SHEET_LIMIT = 31


class ReportError(Exception):
    pass


# --- Per-site figures -------------------------------------------------------------------------------------------------

@dataclass
class Frame:
    """Eligible sites of one period with their pooled figures (arrays aligned with ``sites``)."""
    sites: object  # DataFrame slice of ds.sites
    outage: np.ndarray
    days: np.ndarray
    uptime: np.ndarray
    nsla: np.ndarray
    usd: np.ndarray
    block: np.ndarray
    dates: list = field(default_factory=list)


def frame(ds, period: Period, *, circle: str | None = None, project: str | None = None) -> Frame:
    mask = np.ones(len(ds.sites), dtype=bool)
    if circle:
        mask &= (ds.sites['circle'] == circle).to_numpy()
    if project:
        mask &= (ds.sites['report_type'] == project).to_numpy()
    rows = np.flatnonzero(mask)
    dates = period.dates()
    eligible = metrics.population_eligible(ds, rows, SCOPE, dates)
    rows = rows[eligible]
    block, used = metrics.period_block(metrics.population_view(ds, SCOPE), rows, dates)
    if not block.shape[1]:
        block = np.full((len(rows), 0), np.nan)
    days = (~np.isnan(block)).sum(axis=1)
    outage = np.nansum(block, axis=1) if block.shape[1] else np.zeros(len(rows))
    uptime = metrics.site_uptime(block) if block.shape[1] else np.full(len(rows), np.nan)
    eligible_all = np.ones(len(rows), dtype=bool)
    return Frame(ds.sites.iloc[rows].reset_index(drop=True), outage, days, uptime,
                 metrics.nsla_mask(uptime, eligible_all), metrics.usd_mask(block) if block.shape[1] else np.zeros(len(rows), dtype=bool),
                 block, used)


@dataclass
class Agg:
    n: int
    reported: int
    up: float | None
    nm: int | None
    usd: int | None
    hours: float
    outage_minutes: float
    bk: dict
    bk_minutes: dict

    @property
    def tgt(self):
        return TARGET


def aggregate(f: Frame, idx: np.ndarray | None = None, rca: list[dict] | None = None) -> Agg:
    sel = np.arange(len(f.outage)) if idx is None else idx
    site_days = int(f.days[sel].sum())
    reported = int((f.days[sel] > 0).sum())
    outage = float(f.outage[sel].sum())
    bk = {b: 0.0 for b in BUCKETS}
    bk_minutes = {b: 0.0 for b in BUCKETS}
    for r in rca or []:
        minutes = float(r['outage_minutes'] or 0.0)
        bk_minutes[r['bucket']] += minutes
        bk[r['bucket']] += minutes / 60.0
    return Agg(n=len(sel), reported=reported, up=metrics.uptime_pct(outage, site_days),
               nm=int(f.nsla[sel].sum()) if reported else None, usd=int(f.usd[sel].sum()) if reported else None,
               hours=outage / 60.0, outage_minutes=outage, bk=bk, bk_minutes=bk_minutes)


def status(up, tgt=TARGET) -> str:
    """Reference ``status``: Meets SLA / Minor breach (within 0.5 pp) / Breach, with the portal's rounding."""
    if up is None:
        return 'No data'
    value = float(metrics.comparable(up))
    if value >= tgt:
        return 'Meets SLA'
    if value >= tgt - 0.5:
        return 'Minor breach'
    return 'Breach'


def st_col(up, tgt=TARGET) -> str:
    s = status(up, tgt)
    return {'Meets SLA': '#006300', 'Minor breach': '#8a5a00', 'Breach': '#b42323'}.get(s, '#52514e')


def chg_txt(cur, prev, d) -> str:
    if cur is None or prev is None:
        return ''
    x = cur - prev
    if abs(x) < 10 ** -d / 2:
        return '='
    return ('▲ ' if x > 0 else '▼ ') + fmt(abs(x), d)


def chg_col(cur, prev, hg) -> str:
    if cur is None or prev is None:
        return '#52514e'
    x = cur - prev
    if abs(x) < 1e-9:
        return '#52514e'
    return '#006300' if (x > 0 if hg else x < 0) else '#b42323'


# --- Email body builder (reference RB / rbTable) ----------------------------------------------------------------------

TH = 'background:#14325c;color:#ffffff;padding:6px 9px;border:1px solid #c3c2b7;text-align:left;font-size:12px;white-space:nowrap'
FONT = 'font-family:Segoe UI,Arial,sans-serif'


@dataclass
class Col:
    h: str
    num: bool = False
    f: object = None  # (value, row) -> html
    style: object = None  # (value, row) -> css


class Builder:
    def __init__(self):
        self.html = ''
        self.sheets: list[dict] = []

    def table(self, title: str, cols: list[Col], rows: list[list], sheet: str | None | bool = None, backgrounds: dict | None = None):
        self.html += f'<h3 style="{FONT};font-size:15px;color:#14325c;margin:18px 0 6px">{escape(title)}</h3>'
        self.html += f'<table style="border-collapse:collapse;{FONT};font-size:12.5px"><tr>'
        self.html += ''.join(f'<th style="{TH}{";text-align:right" if c.num else ""}">{escape(c.h)}</th>' for c in cols) + '</tr>'
        if rows:
            for i, r in enumerate(rows):
                bg = (backgrounds or {}).get(i) or ('#f7f7f5' if i % 2 else '#ffffff')
                self.html += f'<tr style="background:{bg}">'
                for j, c in enumerate(cols):
                    v = r[j]
                    style = 'padding:5px 9px;border:1px solid #e1e0d9;white-space:nowrap;' + ('text-align:right;' if c.num else '')
                    style += (c.style(v, r) or '') if c.style else ''
                    body = c.f(v, r) if c.f else escape('' if v is None else str(v))
                    self.html += f'<td style="{style}">{body}</td>'
                self.html += '</tr>'
        else:
            self.html += f'<tr><td colspan="{len(cols)}" style="padding:6px 9px;border:1px solid #e1e0d9;color:#52514e">None</td></tr>'
        self.html += '</table>'
        if sheet is not False:
            self.sheets.append({'name': (sheet or title)[:30], 'rows': [[c.h for c in cols]] + [[_cell(v) for v in r[:len(cols)]] for r in rows]})


def _cell(v):
    if isinstance(v, float):
        return None if v != v else round(v, 3)
    return v


def _num(d):
    return lambda v, r: '–' if v is None or v == '' else fmt(v, d)


# --- Groups ----------------------------------------------------------------------------------------------------------

def _names(series):
    return series.fillna('').astype(str).str.strip().replace({'': 'Unassigned', '-': 'Unassigned', '0': 'Unassigned'})


def groups(f: Frame, column: str) -> dict[str, np.ndarray]:
    keys = _names(f.sites[column]).to_numpy()
    out: dict[str, list[int]] = {}
    for i, k in enumerate(keys):
        out.setdefault(k, []).append(i)
    return {k: np.array(v, dtype=int) for k, v in out.items()}


def ranked(aggs: dict[str, Agg]) -> list[str]:
    """Portal rule: lowest NSLA share first (circle-wise NSLA ranking), higher uptime breaks ties; no data last."""
    def key(k):
        a = aggs[k]
        share = (a.nm / a.n) if a.n and a.nm is not None else float('inf')
        return (share, -(a.up if a.up is not None else -1e9), k)
    return sorted(aggs, key=key)


def site_key(site_id: str) -> str:
    return re.sub(r'\s+', ' ', str(site_id or '').strip()).upper()


def rca_by_site(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r['site_key'], []).append(r)
    return out


def top_cause(rows: list[dict]) -> tuple[str, str]:
    totals: dict[str, float] = {}
    bucket: dict[str, str] = {}
    for r in rows:
        totals[r['cause']] = totals.get(r['cause'], 0.0) + r['hours']
        bucket[r['cause']] = r['bucket']
    if not totals:
        return '', ''
    cause = max(totals, key=lambda k: (totals[k], k))
    return cause, bucket[cause]


# --- Recipients ------------------------------------------------------------------------------------------------------

def recipients(circle_code: str | None, report_type: str) -> dict:
    """Reference ``recips``: active Distribution Master rows of the Circle (None = All India) and report type."""
    qs = DistributionRecipient.objects.filter(is_active=True, report_type=report_type)
    qs = qs.filter(circle__code=circle_code) if circle_code else qs.filter(circle__isnull=True)
    rows = list(qs.order_by('kind', 'name', 'email').values('email', 'kind'))
    return {'to': [r['email'] for r in rows if r['kind'] == DistributionRecipient.Kind.TO],
            'cc': [r['email'] for r in rows if r['kind'] == DistributionRecipient.Kind.CC]}


# --- Report ----------------------------------------------------------------------------------------------------------

def latest_date(ds) -> date:
    if ds.latest_date is None:
        raise ReportError('No complete reporting date is available in the uptime data.')
    return ds.latest_date


def _weeks(end: date, count: int) -> list[tuple[str, Period, bool]]:
    last_sunday = end - timedelta(days=(end.weekday() + 1) % 7)
    out = []
    for i in range(count - 1, -1, -1):
        sunday = last_sunday - timedelta(days=7 * i)
        out.append((d_short(sunday - timedelta(days=6)), Period(sunday - timedelta(days=6), sunday), False))
    return out


def _months(ds, end: date, count: int) -> list[tuple[str, Period, bool]]:
    first = min([m['start'] for m in ds.months] + list(ds.dates[:1])) if (ds.months or ds.dates) else end.replace(day=1)
    out, cur = [], end.replace(day=1)
    while cur >= first.replace(day=1) and len(out) < count:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        last = min(nxt - timedelta(days=1), end)
        out.insert(0, (f"{('Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec')[cur.month - 1]} {str(cur.year)[2:]}",
                       Period(cur, last), last < nxt - timedelta(days=1)))
        cur = (cur - timedelta(days=1)).replace(day=1)
    return out


def build(ds, report_type: str, circle: dict | None, *, project: str = '', pairs=None, source: str = '') -> dict:
    """One report email. ``circle``: {"code", "name"} or None for the All India summary. ``ds``: the On-Air dataset
    already limited to the user's pairs; ``pairs`` limits the RCA rows the same way."""
    if report_type not in (ReportType.D1, ReportType.WEEKLY):
        raise ReportError('Choose the D-1 or Weekly report.')
    latest = latest_date(ds)
    period = report_period(report_type, latest)
    prev, mtd = period.previous(), period.month_to_date()
    code = circle['code'] if circle else None
    scope_lbl = circle['name'] if circle else 'All India'
    if project:
        scope_lbl += f' ({project})'
    if report_type == ReportType.D1:
        title = f'D-1 4G Site Performance – {scope_lbl} – {d_long(period.start)}'
    else:
        title = f'Weekly 4G Site Performance – {scope_lbl} – {d_short(period.start)} to {d_short(period.end)} {period.end.year}'
    projects = [project] if project else None
    circles = [code] if code else None

    week_buckets = _weeks(period.end, 8) if report_type == ReportType.WEEKLY else []
    month_buckets = _months(ds, period.end, 6) if report_type == ReportType.WEEKLY else []
    span = Period(min([prev.start, mtd.start] + [p.start for _, p, _ in week_buckets + month_buckets]), period.end)
    rca_all = rca_rows(span, circles=circles, projects=projects, pairs=pairs)

    def rca_in(p: Period):
        return [r for r in rca_all if p.start <= r['reporting_date'] <= p.end]

    data_status = period_status(ds, period, circle=code, project=project)
    F, PF, MF = frame(ds, period, circle=code, project=project), frame(ds, prev, circle=code, project=project), frame(ds, mtd, circle=code, project=project)
    rca_cur = rca_in(period)
    A, PA, MA = aggregate(F, rca=rca_cur), aggregate(PF, rca=rca_in(prev)), aggregate(MF, rca=rca_in(mtd))
    if not A.n:
        raise ReportError(f'No On-Air sites in {scope_lbl} for this period.')
    cur_lbl, prev_lbl = ('D-1', 'D-2') if report_type == ReportType.D1 else ('This week', 'Previous week')
    R = Builder()
    period_txt = d_long(period.start) if report_type == ReportType.D1 else f'{d_short(period.start)} to {d_short(period.end)}'
    up_txt = f'{fmt(A.up, 3)}%' if A.up is not None else 'not available'
    R.html += (f'<div style="{FONT};font-size:14px;color:#111"><p>Dear All,</p><p>Please find the '
               f'{"D-1" if report_type == ReportType.D1 else "weekly"} 4G site performance report for <b>{escape(scope_lbl)}</b> for {period_txt}.</p>'
               f'<p style="font-size:15px">Uptime <b style="color:{st_col(A.up)}">{up_txt}</b> against target {fmt(TARGET, 2)}% '
               f'({status(A.up)}), {chg_txt(A.up, PA.up, 2) or "–"} pp vs {prev_lbl}. {fmt(A.nm)} of {fmt(A.n)} sites missed SLA; '
               f'{fmt(A.usd)} sites had an outage (USD), {fmt(whole_minutes(A.outage_minutes))} Outage Minutes. Month-to-date uptime '
               f'{fmt(MA.up, 3)}%.</p>{_status_note(data_status)}</div>')

    kpis = [('Uptime %', A.up, PA.up, MA.up, 2, True), ('SLA target %', TARGET, TARGET, TARGET, 2, None),
            ('Sites not meeting SLA', A.nm, PA.nm, MA.nm, 0, False), ('USD sites', A.usd, PA.usd, MA.usd, 0, False),
            ('Outage Minutes', whole_minutes(A.outage_minutes), whole_minutes(PA.outage_minutes), whole_minutes(MA.outage_minutes), 0, False),
            ('Customer-bucket Outage Minutes', whole_minutes(A.bk_minutes[Bucket.CUSTOMER]),
             whole_minutes(PA.bk_minutes[Bucket.CUSTOMER]), whole_minutes(MA.bk_minutes[Bucket.CUSTOMER]), 0, None)]
    krows = []
    for name, cur, prv, mt, d, hg in kpis:
        row = [name, cur, prv, chg_txt(cur, prv, d) if hg is not None else '']
        if report_type == ReportType.D1:
            row.append(mt)
        row += [d, hg]
        krows.append(row)
    kcols = [Col('KPI'), Col(cur_lbl, True, lambda v, r: '<b>' + fmt(v, r[-2]) + '</b>'),
             Col(prev_lbl, True, lambda v, r: fmt(v, r[-2])),
             Col('Change', True, lambda v, r: v or '–',
                 lambda v, r: f'color:{chg_col(r[1], r[2], r[-1])};font-weight:600' if v and r[-1] is not None else '')]
    if report_type == ReportType.D1:
        kcols.append(Col('Month to date', True, lambda v, r: fmt(v, r[-2])))
    R.table('KPI summary', kcols, krows, 'KPI summary')

    trow = lambda lbl, part, a: [lbl + (' *' if part else ''), a.up, a.nm, a.usd,  # noqa: E731
                                 whole_minutes(a.outage_minutes), whole_minutes(a.bk_minutes[Bucket.CUSTOMER])]
    tcols = lambda lbl: [Col(lbl), Col('Uptime %', True, _num(3), lambda v, r: f'color:{st_col(v)};font-weight:600'),  # noqa: E731
                         Col('Not meeting SLA', True, _num(0)), Col('USD sites', True, _num(0)),
                         Col('Outage Minutes', True, _num(0)), Col('Customer-bucket Outage Minutes', True, _num(0))]
    if report_type == ReportType.WEEKLY:
        weeks = [trow(lbl, part, aggregate(frame(ds, p, circle=code, project=project), rca=rca_in(p))) for lbl, p, part in week_buckets]
        R.table('Week-wise trend – last 8 weeks', tcols('Week starting'), weeks, 'Week-wise trend')
        months = [trow(lbl, part, aggregate(frame(ds, p, circle=code, project=project), rca=rca_in(p))) for lbl, p, part in month_buckets]
        R.table('Month-wise trend (* = partial month)', tcols('Month'), months, 'Month-wise trend')

    child_col = 'ci_name' if circle else 'circle'
    child_lbl = 'Cluster / CI' if circle else 'Circle'
    names = _circle_names(ds) if not circle else {}
    cur_groups, prev_groups = groups(F, child_col), groups(PF, child_col)
    by_site_cur = rca_by_site(rca_cur)
    keys_cur = F.sites['site_id'].map(site_key).to_numpy()

    def group_rca(f_keys, idx, by_site):
        return [r for k in set(f_keys[idx]) for r in by_site.get(k, [])]
    cur_aggs = {k: aggregate(F, idx, group_rca(keys_cur, idx, by_site_cur)) for k, idx in cur_groups.items()}
    prev_aggs = {k: aggregate(PF, idx) for k, idx in prev_groups.items()}
    order, prev_order = ranked(cur_aggs), ranked(prev_aggs)
    prev_rank = {k: i + 1 for i, k in enumerate(prev_order)}
    rank_rows, bgs = [], {}
    for i, k in enumerate(order):
        a = cur_aggs[k]
        delta = prev_rank[k] - (i + 1) if k in prev_rank else ''
        rank_rows.append([i + 1, delta, names.get(k, k), a.n, a.up, status(a.up), a.nm, a.usd, whole_minutes(a.outage_minutes)])
        if len(order) >= 6 and i >= len(order) - 3:
            bgs[i] = '#fbe5e5'
    R.table(f'{"CI" if circle else "Circle"} ranking ({cur_lbl})',
            [Col('Rank', True), Col('Δ rank', True, lambda v, r: '–' if v == '' else (f'▲ {v}' if v > 0 else f'▼ {-v}' if v < 0 else '='),
                                    lambda v, r: 'color:#006300' if v != '' and v > 0 else 'color:#b42323' if v != '' and v < 0 else ''),
             Col(child_lbl), Col('Sites', True), Col('Uptime %', True, _num(3), lambda v, r: f'color:{st_col(v)};font-weight:600'),
             Col('Status'), Col('Not meeting SLA', True, _num(0)), Col('USD sites', True, _num(0)), Col('Outage Minutes', True, _num(0))],
            rank_rows, 'CI ranking' if circle else 'Circle ranking', bgs)

    if circle:
        ne_groups = groups(F, 'ie_name')
        ci_names = _names(F.sites['ci_name']).to_numpy()
        ne_rows = []
        for k, idx in ne_groups.items():
            a = aggregate(F, idx)
            values, counts = np.unique(ci_names[idx], return_counts=True)
            ne_rows.append([k, values[np.argmax(counts)], a.n, a.up, a.nm, a.usd, whole_minutes(a.outage_minutes)])
        ne_rows.sort(key=lambda r: (r[3] if r[3] is not None else 1e9, r[0]))
        R.table('NE performance – weakest first',
                [Col('NE'), Col('Cluster'), Col('Sites', True), Col('Uptime %', True, _num(3), lambda v, r: f'color:{st_col(v)};font-weight:600'),
                 Col('Not meeting SLA', True, _num(0)), Col('USD sites', True, _num(0)), Col('Outage Minutes', True, _num(0))],
                ne_rows[:10] if report_type == ReportType.D1 else ne_rows, 'NE performance')

    nm_idx = [i for i in np.argsort(np.nan_to_num(F.uptime, nan=1e9), kind='stable') if F.nsla[i]]
    nm_rows = []
    for i in nm_idx[: 25 if report_type == ReportType.D1 else 40]:
        s = F.sites.iloc[i]
        cause, bk = top_cause(by_site_cur.get(keys_cur[i], []))
        nm_rows.append([s['site_id'], _names(F.sites['ie_name'].iloc[[i]]).iloc[0], s['report_type'], float(F.uptime[i]), TARGET,
                        'Yes' if F.usd[i] else '', whole_minutes(F.outage[i]), cause, responsibility_label(bk)])
    R.table(f'Sites not meeting SLA ({len(nm_idx)})',
            [Col('Site'), Col('NE'), Col('Category'), Col('Uptime %', True, _num(3)), Col('Target %', True, _num(2)), Col('USD'),
             Col('Outage Minutes', True, _num(0)), Col('Main RCA'), Col('Bucket')], nm_rows, 'Not meeting SLA')

    tb = sum(A.bk_minutes.values()) or 1e-9
    R.table('Outage Minutes by RCA bucket', [Col('Bucket'), Col('Outage Minutes', True, _num(0)), Col('Share', True, lambda v, r: fmt(v, 1) + '%'), Col('SLA treatment')],
            [[responsibility_label(b), whole_minutes(A.bk_minutes[b]), A.bk_minutes[b] / tb * 100,
              'Claim exclusion' if b in EXCLUDABLE else 'Counts against SLA' if b == Bucket.OWN else 'Unclassified' if b == Bucket.UNCLASSIFIED else 'Close RCA']
             for b in BUCKETS], 'RCA buckets')

    if report_type == ReportType.WEEKLY:
        day_rows = []
        for j, day in enumerate(F.dates):
            col = F.block[:, j]
            n = int((~np.isnan(col)).sum())
            down = float(np.nansum(col))
            day_rows.append([d_short(day), metrics.uptime_pct(down, n), whole_minutes(down)])
        R.table('Day-wise uptime', [Col('Date'), Col('Uptime %', True, _num(3), lambda v, r: f'color:{st_col(v)};font-weight:600'),
                                    Col('Outage Minutes', True, _num(0))], day_rows, 'Day-wise')
        cz: dict[str, float] = {}
        czb: dict[str, str] = {}
        for r in rca_cur:
            cz[r['cause']] = cz.get(r['cause'], 0.0) + float(r['outage_minutes'] or 0.0)
            czb[r['cause']] = r['bucket']
        ct = sum(cz.values()) or 1e-9
        R.table('Root cause split', [Col('Root cause'), Col('Bucket'), Col('Outage Minutes', True, _num(0)), Col('Share', True, lambda v, r: fmt(v, 1) + '%')],
                [[k, czb[k], whole_minutes(v), v / ct * 100] for k, v in sorted(cz.items(), key=lambda kv: (-kv[1], kv[0]))], 'Root cause')

    R.html += (f'<p style="{FONT};font-size:13px;color:#52514e;margin-top:18px">Detailed site-level data is attached. This report is '
               f'generated automatically from the BSNL 4G Portal ({escape(source or "uptime data")}; RCA records).<br>Regards,<br>NOC / MIS Team</p>')

    all_rows = []
    order_all = np.argsort(np.nan_to_num(F.uptime, nan=1e9), kind='stable')
    ie_all, ci_all = _names(F.sites['ie_name']).to_numpy(), _names(F.sites['ci_name']).to_numpy()
    for i in order_all:
        s = F.sites.iloc[i]
        site_rows = by_site_cur.get(keys_cur[i], [])
        cause, _ = top_cause(site_rows)
        up = None if np.isnan(F.uptime[i]) else round(float(F.uptime[i]), 3)
        all_rows.append([s['site_id'], s['site_name'], s['circle'], ci_all[i], ie_all[i], s['report_type'], up, TARGET, status(up),
                         'Yes' if F.usd[i] else '', whole_minutes(F.outage[i]),
                         whole_minutes(sum(float(r['outage_minutes'] or 0.0) for r in site_rows if r['bucket'] == Bucket.CUSTOMER)),
                         whole_minutes(sum(float(r['outage_minutes'] or 0.0) for r in site_rows if r['bucket'] == Bucket.THIRD_PARTY)), cause])
    R.sheets.append({'name': 'All sites', 'rows': [['Site ID', 'Site Name', 'Circle', 'Cluster', 'NE', 'Category', 'Uptime %', 'Target %',
                                                    'Status', 'USD', 'Outage Minutes', 'Customer-bucket Outage Minutes',
                                                    'Third-party Outage Minutes', 'Main RCA']] + all_rows})

    rc = recipients(code, report_type if circle else ReportType.ALL_INDIA)
    return {'title': title, 'subject': title, 'html': R.html, 'sheets': R.sheets, 'to': rc['to'], 'cc': rc['cc'],
            'period': {'start': period.start.isoformat(), 'end': period.end.isoformat(), 'label': period_txt},
            'file': re.sub(r'[^\w\-]+', '_', title, flags=re.ASCII), 'kpis': _agg_json(A), 'report_type': report_type,
            'circle': code or '', 'project': project, 'data_status': data_status}


def period_status(ds, period: Period, *, circle: str | None = None, project: str | None = None) -> dict:
    """The portal's Complete / Provisional status of the period for the report's own reporting units (approved rule B-7:
    a date is never dropped; a provisional one is labelled with the units still missing)."""
    mask = np.ones(len(ds.sites), dtype=bool)
    if circle:
        mask &= (ds.sites['circle'] == circle).to_numpy()
    if project:
        mask &= (ds.sites['report_type'] == project).to_numpy()
    result = metrics.dates_status(ds, period.dates(), metrics.units_of_rows(ds, np.flatnonzero(mask)))
    if not result:
        return {'status': None, 'missing': []}
    return {'status': result['status'], 'missing': result['missing']}


def _status_note(data_status: dict) -> str:
    if data_status.get('status') != 'Provisional':
        return ''
    units = sorted({u for m in data_status['missing'] for u in m['units']})
    return (f'<p style="font-size:13px;color:#8a5a00">Data status: Provisional – data not yet received for '
            f'{escape(", ".join(units))}. Figures may change when it arrives.</p>')


def _agg_json(a: Agg) -> dict:
    return {'sites': a.n, 'sites_reported': a.reported, 'uptime_pct': a.up, 'target_pct': TARGET, 'status': status(a.up),
            'not_meeting_sla': a.nm, 'usd_sites': a.usd, 'outage_minutes': whole_minutes(a.outage_minutes),
            'customer_minutes': whole_minutes(a.bk_minutes[Bucket.CUSTOMER]),
            'outage_hours': round(a.hours, 2), 'customer_hours': round(a.bk[Bucket.CUSTOMER], 2)}


def _circle_names(ds) -> dict[str, str]:
    from apps.organization.models import Circle
    codes = set(ds.sites['circle'])
    return dict(Circle.objects.filter(code__in=codes).values_list('code', 'name'))


def circle_overview(ds, report_type: str, project: str = '') -> dict:
    """The distribution table: each Circle's figures for the report period (reference pageAuto list)."""
    latest = latest_date(ds)
    period = report_period(report_type, latest)
    F = frame(ds, period, project=project)
    names = _circle_names(ds)
    rows = []
    for code, idx in sorted(groups(F, 'circle').items(), key=lambda kv: names.get(kv[0], kv[0])):
        a = aggregate(F, idx)
        rows.append({'circle': code, 'name': names.get(code, code), **_agg_json(a), **recipients(code, report_type)})
    for row in rows:
        row['data_status'] = period_status(ds, period, circle=row['circle'], project=project)
    return {'period': {'start': period.start.isoformat(), 'end': period.end.isoformat(),
                       'label': d_long(period.start) if report_type == ReportType.D1 else f'{d_short(period.start)} – {d_short(period.end)}'},
            'latest_date': latest.isoformat(), 'circles': rows, 'all_india': recipients(None, ReportType.ALL_INDIA),
            'data_status': period_status(ds, period, project=project)}


def minutes_check(f: Frame) -> float:
    """Total outage minutes of a frame (used by tests to reconcile with the dashboard)."""
    return float(f.outage.sum()) if len(f.outage) else 0.0


__all__ = ['build', 'circle_overview', 'frame', 'aggregate', 'ReportError', 'MINUTES_PER_DAY']

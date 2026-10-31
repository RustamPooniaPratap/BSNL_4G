"""Master Data: the business datasets the database explorer may show, each a read-only view of an existing table.

A dataset is registered once here (columns, filters, time field); the list, options and export endpoints are generic.
Adding a dataset means adding one ``Dataset`` to ``DATASETS``. Only these tables are reachable: no authentication,
session or system table is ever exposed.

Period views (time-based datasets only), on the dataset's own date field:
- daily: one month (year and month), optionally one date;
- weekly: one reporting week of a month, as everywhere in the portal (days 1-7, 8-14, 15-21, 22-end: metrics.WEEKS);
- monthly: a range of months;
- overall: every date, optionally a date range.
The uptime "monthly" view reads the stored monthly records (SiteMonthlyPerformance), never a new aggregation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from django.db.models import QuerySet

from apps.rca.models import RcaRecord
from apps.uptimedb.models import EscalationSite, SiteDailyPerformance, SiteMonthlyPerformance, UptimeSite


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    field: str  # ORM path
    kind: str = 'text'  # text | number | pct | date | datetime | bool | minutes
    contact: bool = False  # phone numbers: Admins only
    hidden: bool = False  # shown only when the user turns it on


@dataclass(frozen=True)
class Choice:
    """A dataset-specific filter on one field, its options read from the data."""
    key: str
    label: str
    field: str


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    description: str
    queryset: Callable[[], QuerySet]
    columns: tuple[Column, ...]
    project: str
    circle: str
    site_id: str | None = None
    site_name: str | None = None
    date: str | None = None  # time field: enables the period views
    month: str | None = None  # a month-grain dataset (first day of the month)
    choices: tuple[Choice, ...] = ()
    default_sort: str = 'id'
    search: tuple[str, ...] = field(default=())


def _c(key, label, path=None, kind='text', **kw):
    return Column(key, label, path or key, kind, **kw)


SITE = (_c('project', 'Project', 'site__project'), _c('circle', 'Circle', 'site__circle'), _c('site_id', 'Site ID', 'site__site_id'),
        _c('site_name', 'Site name', 'site__site_name'))

DATASETS: dict[str, Dataset] = {d.key: d for d in (
    Dataset(
        'uptime_sites', 'Site Master', 'Approved sites of the Up-Time Report, one row per project, circle and site.',
        lambda: UptimeSite.objects.select_related('batch'),
        (_c('project', 'Project'), _c('circle', 'Circle'), _c('site_id', 'Site ID'), _c('site_name', 'Site name'), _c('oa', 'OA'), _c('ba', 'BA'),
         _c('on_air', 'On-Air', kind='bool'), _c('on_air_raw', 'On-Air (as written)', hidden=True), _c('eb', 'EB'),
         _c('od_eb_working_status', 'EB working status'), _c('solar_logic_done', 'Solar Logic Done'),
         _c('ie_name', 'IE name'), _c('ie_contact', 'IE contact', contact=True), _c('ci_name', 'CI name'), _c('ci_contact', 'CI contact', contact=True),
         _c('circle_raw', 'Circle (as written)', hidden=True), _c('project_raw', 'Project (as written)', hidden=True),
         _c('source_file', 'Source file', hidden=True), _c('source_row', 'Source row', kind='number', hidden=True),
         _c('updated_at', 'Updated', kind='datetime', hidden=True)),
        project='project', circle='circle', site_id='site_id', site_name='site_name',
        choices=(Choice('oa', 'OA', 'oa'), Choice('on_air', 'On-Air', 'on_air')), default_sort='site_id',
        search=('site_id', 'site_name', 'oa', 'ba', 'ie_name', 'ci_name')),
    Dataset(
        'uptime_daily', 'Daily Performance', 'Daily outage and uptime per site and reporting date.',
        lambda: SiteDailyPerformance.objects.select_related('site', 'batch'),
        (_c('date', 'Reporting date', kind='date'), *SITE, _c('oa', 'OA', 'site__oa'),
         _c('uptime_pct', 'Availability', kind='pct'), _c('outage_minutes', 'Outage minutes', kind='minutes'),
         _c('source', 'Source', 'batch__kind'), _c('batch', 'Import #', 'batch_id', kind='number', hidden=True)),
        project='site__project', circle='site__circle', site_id='site__site_id', site_name='site__site_name', date='date',
        default_sort='-date', search=('site__site_id', 'site__site_name', 'site__oa')),
    Dataset(
        'uptime_monthly', 'Monthly Performance', 'Monthly outage, uptime and threshold bucket per site, as stored.',
        lambda: SiteMonthlyPerformance.objects.select_related('site'),
        (_c('month', 'Month', kind='month'), *SITE, _c('uptime_pct', 'Availability', kind='pct'), _c('outage_minutes', 'Outage minutes', kind='minutes'),
         _c('bucket', 'Bucket'), _c('ff_count', 'FF count', kind='number'), _c('om_start_raw', 'O&M Start')),
        project='site__project', circle='site__circle', site_id='site__site_id', site_name='site__site_name', month='month',
        choices=(Choice('bucket', 'Bucket', 'bucket'),), default_sort='-month', search=('site__site_id', 'site__site_name')),
    Dataset(
        'escalation', 'CI-wise Consolidation & Escalation Matrix', 'The Consolidated Escalation Matrix ("Raw Data"): one row per site.',
        lambda: EscalationSite.objects.all(),
        (_c('project', 'Entity'), _c('circle', 'Circle'), _c('site_id', 'BSNL Site ID'), _c('site_name', 'Site name'), _c('site_type', 'Site type'),
         _c('ba', 'BA'), _c('oa', 'OA'), _c('district', 'District'), _c('sub_district', 'Sub-district'), _c('village_code', 'Village code', hidden=True),
         _c('commissioning_date', 'Commissioning', kind='date'), _c('commissioning_status', 'Commissioning status'),
         _c('on_air_status', 'On-Air status'), _c('on_air_date', 'On-Air date', kind='date'),
         _c('om_status', 'O&M status'), _c('om_start_date', 'O&M Start date', kind='date'),
         _c('eb_status', 'EB status'), _c('dg_status', 'DG status'), _c('case_type', 'Case type', hidden=True),
         _c('ci_emp_code', 'CI emp. code', hidden=True), _c('ci_name', 'CI'), _c('ci_contact', 'CI contact', contact=True),
         _c('ie_emp_code', 'IE emp. code', hidden=True), _c('ie_name', 'IE'), _c('ie_contact', 'IE contact', contact=True),
         _c('il_name', 'IL'), _c('il_contact', 'IL contact', contact=True),
         _c('om_manager_name', 'O&M Manager'), _c('om_manager_contact', 'O&M Manager contact', contact=True),
         _c('cbh_name', 'CBH'), _c('cbh_contact', 'CBH contact', contact=True),
         _c('ct_status', 'CT status', hidden=True), _c('ct_name', 'CT', hidden=True), _c('ct_contact', 'CT contact', contact=True, hidden=True),
         _c('rigger_name', 'Rigger', hidden=True), _c('rigger_contact', 'Rigger contact', contact=True, hidden=True),
         _c('latitude', 'Latitude', kind='number', hidden=True), _c('longitude', 'Longitude', kind='number', hidden=True),
         _c('site_address', 'Address', hidden=True), _c('smps_make', 'SMPS make', hidden=True),
         _c('bts_id_b1', 'BTS ID B1 (21 MHz)', hidden=True), _c('bts_id_b28', 'BTS ID B28 (7 MHz)', hidden=True),
         _c('master_bts_id', 'Master BTS ID', hidden=True), _c('match_status', 'Up-Time match'), _c('remarks', 'Remarks', hidden=True)),
        project='project', circle='circle', site_id='site_id', site_name='site_name',
        choices=(Choice('ba', 'BA', 'ba'), Choice('ci_name', 'CI', 'ci_name'), Choice('om_status', 'O&M status', 'om_status')),
        default_sort='site_id', search=('site_id', 'site_name', 'ba', 'oa', 'district', 'ci_name', 'ie_name')),
    Dataset(
        'rca', 'RCA Data', 'Accepted RCA records (incidents); a site can have several on one date.',
        lambda: RcaRecord.objects.select_related('batch', 'batch__imported_by'),
        (_c('reporting_date', 'Date', kind='date'), _c('project', 'Project'), _c('circle', 'Circle'), _c('site_id', 'Site ID'),
         _c('site_name', 'Site name'), _c('oa', 'OA'), _c('ba', 'BA'), _c('om_start_raw', 'O&M Start'),
         _c('outage_minutes', 'Outage minutes', kind='minutes'), _c('final_bucket', 'Final Bucket'), _c('bucket_2', 'Bucket - 2'),
         _c('rca_text', 'RCA'), _c('occurrence', 'Incident # of the day', kind='number', hidden=True),
         _c('source', 'Recorded by'), _c('source_file', 'Source file', hidden=True), _c('source_row', 'Source row', kind='number', hidden=True),
         _c('upload_type', 'Upload type', 'batch__upload_type', hidden=True), _c('uploaded_by', 'Uploaded by', 'batch__imported_by__username', hidden=True)),
        project='project', circle='circle', site_id='site_id', site_name='site_name', date='reporting_date',
        choices=(Choice('final_bucket', 'Final Bucket', 'final_bucket'), Choice('bucket_2', 'Bucket - 2', 'bucket_2')),
        default_sort='-reporting_date', search=('site_id', 'site_name', 'oa', 'ba', 'rca_text')),
)}

"""Master Data: the business datasets the database explorer may show, each a view of one table of the data layer.

A dataset is registered once here (columns, filters, time field); the list, options and export endpoints are generic.
Adding a dataset means adding one ``Dataset`` to ``DATASETS``. Only these tables are reachable: no authentication,
session or system table is ever exposed. The dataset KEYS are permanent: they name the permission modules
``data_<key>`` (accounts.catalog) that roles are granted, so a key is never renamed.

Sources (apps.sitedata is the only operational data layer):
- Site Master (``uptime_sites``): sitedata.Site, dashboard and outside-scope sites with their Consolidation Matrix
  attributes. Read-only: the matrix is authoritative and changes only through the matrix import.
- Daily Performance (``uptime_daily``): sitedata.DailySitePerformance. Editable only as authorized corrections with a
  reason (editors.DailyEditor -> sitedata.daily.correct / add_correction).
- Monthly Performance (``uptime_monthly``): the current sitedata.MonthlySitePerformance results. Read-only.
- Escalation Matrix (``escalation``): the matrix contact / escalation columns of sitedata.Site. Read-only.
- RCA Data (``rca``): apps.rca records.
The project of a site-data record is its technology (4G Saturation / LWE); outside-scope sites have none.

Period views (time-based datasets only), on the dataset's own date field:
- daily: one month (year and month), optionally one date;
- weekly: one reporting week of a month, as everywhere in the portal (days 1-7, 8-14, 15-21, 22-end: metrics.WEEKS);
- monthly: a range of months;
- overall: every date, optionally a date range.
The "monthly" view of Daily Performance reads the stored monthly results (MonthlySitePerformance), never a new aggregation.

Site population filter (``scope``: on_air | om_start, optional; absent = no population filter, every record as stored;
any other value is HTTP 400) on the site-based datasets (``Dataset.population``), with the portal's effective-date rule
(Consolidation Matrix Site On-Air Date / O&M Start Date; dashboard-scope sites only):
- Site Master and Escalation Matrix (``site``): sites effective today (date on or before today);
- Daily Performance (``daily``): records whose site is effective on the record's reporting date;
- Monthly Performance (``monthly``): results whose site is effective in that month (date on or before the month's end).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from django.db.models import QuerySet

from apps.rca.models import RcaRecord
from apps.sitedata.models import DailySitePerformance, MonthlySitePerformance, Site


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
    # Site population filter (``scope``): 'site' (a sitedata.Site row), 'daily' (a daily record), 'monthly' (a monthly
    # result); None: the dataset has no population (RCA records).
    population: str | None = None


def _c(key, label, path=None, kind='text', **kw):
    return Column(key, label, path or key, kind, **kw)


SITE = (_c('project', 'Project', 'technology'), _c('circle', 'Circle', 'site__circle'), _c('site_id', 'Site ID', 'site__bsnl_site_id'),
        _c('site_name', 'Site name', 'site__site_name'))

DATASETS: dict[str, Dataset] = {d.key: d for d in (
    Dataset(
        'uptime_sites', 'Site Master',
        'Every site of the Consolidation Matrix (dashboard and outside-scope), one row per BSNL Site ID. Read-only: the '
        'matrix is authoritative and changes only through the matrix import.',
        lambda: Site.objects.all(),
        (_c('project', 'Project', 'technology'), _c('entity', 'Entity', hidden=True), _c('circle', 'Circle'),
         _c('site_id', 'Site ID', 'bsnl_site_id'), _c('site_name', 'Site name'), _c('oa', 'OA'), _c('ba', 'BA'), _c('district', 'District'),
         _c('on_air_status', 'On-Air status'), _c('on_air', 'On-Air', kind='bool', hidden=True), _c('on_air_date', 'On-Air date', kind='date'),
         _c('om_status', 'O&M status'), _c('om_start_date', 'O&M Start date', kind='date'),
         _c('ie_name', 'IE name'), _c('ie_contact', 'IE contact', contact=True), _c('ci_name', 'CI name'), _c('ci_contact', 'CI contact', contact=True),
         _c('reporting_scope', 'Reporting scope'), _c('present_in_latest_matrix', 'In latest matrix', kind='bool'),
         _c('om_start_date_issue', 'O&M Start Date issue', hidden=True), _c('on_air_date_issue', 'On-Air Date issue', hidden=True),
         _c('circle_raw', 'Circle (as written)', hidden=True), _c('source_row', 'Matrix row', kind='number', hidden=True),
         _c('matrix_batch', 'Matrix upload #', 'matrix_batch_id', kind='number', hidden=True),
         _c('updated_at', 'Updated', kind='datetime', hidden=True)),
        project='technology', circle='circle', site_id='bsnl_site_id', site_name='site_name',
        choices=(Choice('oa', 'OA', 'oa'), Choice('on_air', 'On-Air', 'on_air'), Choice('reporting_scope', 'Reporting scope', 'reporting_scope')),
        default_sort='site_id', search=('bsnl_site_id', 'site_name', 'oa', 'ba', 'district', 'ie_name', 'ci_name'), population='site'),
    Dataset(
        'uptime_daily', 'Daily Performance',
        'Daily availability and outage per site and reporting date (the central daily records). A change is an '
        'authorized correction and needs a reason.',
        lambda: DailySitePerformance.objects.select_related('site', 'batch'),
        (_c('date', 'Reporting date', 'report_date', kind='date'), _c('project', 'Project', 'technology'), _c('circle', 'Circle'),
         _c('site_id', 'Site ID', 'site__bsnl_site_id'), _c('site_name', 'Site name', 'site__site_name'), _c('oa', 'OA', 'site__oa'),
         _c('availability_pct', 'Availability', kind='pct'), _c('outage_minutes', 'Outage minutes', kind='minutes'),
         _c('source', 'Source', 'batch__kind'), _c('revision', 'Revision', kind='number'),
         _c('batch', 'Upload #', 'batch_id', kind='number', hidden=True), _c('updated_at', 'Updated', kind='datetime', hidden=True)),
        project='technology', circle='circle', site_id='site__bsnl_site_id', site_name='site__site_name', date='report_date',
        choices=(Choice('source', 'Source', 'batch__kind'),), default_sort='-date',
        search=('site__bsnl_site_id', 'site__site_name', 'site__oa'), population='daily'),
    Dataset(
        'uptime_monthly', 'Monthly Performance',
        'Current monthly results per site (read-only): calculated from the daily records, or imported historical monthly totals '
        '(category "Historical monthly total", no reporting-day count).',
        lambda: MonthlySitePerformance.objects.filter(is_current=True).select_related('site'),
        (_c('month', 'Month', kind='month'), *SITE, _c('category', 'Category', 'calculation_category'),
         _c('availability_pct', 'Availability', kind='pct'), _c('outage_minutes', 'Outage minutes', 'total_outage_minutes', kind='minutes'),
         _c('reporting_days', 'Reporting days', kind='number'), _c('calendar_days', 'Calendar days', kind='number'),
         _c('effective_from', 'Counted from', kind='date', hidden=True), _c('revision', 'Revision', kind='number', hidden=True),
         _c('finalized_at', 'Finalized', kind='datetime', hidden=True)),
        project='technology', circle='site__circle', site_id='site__bsnl_site_id', site_name='site__site_name', month='month',
        choices=(Choice('category', 'Category', 'calculation_category'),), default_sort='-month',
        search=('site__bsnl_site_id', 'site__site_name'), population='monthly'),
    Dataset(
        'escalation', 'CI-wise Consolidation & Escalation Matrix',
        'The contact and escalation columns of the Consolidation Matrix, one row per site (read-only; they change only '
        'through the matrix import).',
        lambda: Site.objects.all(),
        (_c('project', 'Project', 'technology'), _c('entity', 'Entity'), _c('circle', 'Circle'), _c('site_id', 'BSNL Site ID', 'bsnl_site_id'),
         _c('site_name', 'Site name'), _c('site_type', 'Site type'),
         _c('ba', 'BA'), _c('oa', 'OA'), _c('district', 'District'), _c('sub_district', 'Sub-district'), _c('village_code', 'Village code', hidden=True),
         _c('commissioning_date', 'Commissioning', kind='date'), _c('commissioning_status', 'Commissioning status'),
         _c('on_air_status', 'On-Air status'), _c('on_air_date', 'On-Air date', kind='date'),
         _c('om_status', 'O&M status'), _c('om_start_date', 'O&M Start date', kind='date'),
         _c('eb_status', 'EB status'), _c('dg_status', 'DG status'), _c('case_type', 'Case type', hidden=True),
         _c('ci_emp_code', 'CI emp. code', hidden=True), _c('ci_name', 'CI'), _c('ci_contact', 'CI contact', contact=True),
         _c('ie_emp_code', 'IE emp. code', hidden=True), _c('ie_name', 'IE'), _c('ie_contact', 'IE contact', contact=True),
         _c('il_emp_code', 'IL emp. code', hidden=True), _c('il_name', 'IL'), _c('il_contact', 'IL contact', contact=True),
         _c('om_manager_emp_code', 'O&M Manager emp. code', hidden=True),
         _c('om_manager_name', 'O&M Manager'), _c('om_manager_contact', 'O&M Manager contact', contact=True),
         _c('cbh_name', 'CBH'), _c('cbh_contact', 'CBH contact', contact=True),
         _c('ct_status', 'CT status', hidden=True), _c('ct_name', 'CT', hidden=True), _c('ct_contact', 'CT contact', contact=True, hidden=True),
         _c('rigger_emp_code', 'Rigger emp. code', hidden=True),
         _c('rigger_name', 'Rigger', hidden=True), _c('rigger_contact', 'Rigger contact', contact=True, hidden=True),
         _c('latitude', 'Latitude', kind='number', hidden=True), _c('longitude', 'Longitude', kind='number', hidden=True),
         _c('site_address', 'Address', hidden=True), _c('smps_make', 'SMPS make', hidden=True),
         _c('reporting_scope', 'Reporting scope', hidden=True), _c('present_in_latest_matrix', 'In latest matrix', kind='bool', hidden=True),
         _c('remarks', 'Remarks', hidden=True)),
        project='technology', circle='circle', site_id='bsnl_site_id', site_name='site_name',
        choices=(Choice('ba', 'BA', 'ba'), Choice('ci_name', 'CI', 'ci_name'), Choice('om_status', 'O&M status', 'om_status')),
        default_sort='site_id', search=('bsnl_site_id', 'site_name', 'ba', 'oa', 'district', 'ci_name', 'ie_name'), population='site'),
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

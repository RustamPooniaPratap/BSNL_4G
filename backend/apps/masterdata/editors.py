"""Data Panel editing: which datasets can be changed, and the rules a change must follow.

One ``Editor`` per editable dataset of ``datasets.DATASETS`` (``EDITORS``). A dataset without an editor is read-only
(View / Export only): Monthly Performance. Site Master and Escalation Matrix edits are field-scoped manual overrides;
matrix imports retain them and advance the stored matrix value for reversion. Nothing here deletes a record.

- Daily Performance (``DailyEditor``): every change is an authorized correction of the central daily records
  (apps.sitedata.daily.correct for a stored value, add_correction for a site-day without one), with the reason given
  for the save. The correction upload and its DailyPerformanceEvent are the provenance; the value then has the highest
  source precedence. The value may be given as availability % or as outage minutes (apps.sitedata.rules converts).
  Writes into a finalized month are refused (daily.FinalizedPeriod). The save is generic per dataset in
  ``editing.save``: permissions and project/circle scope (the project of a daily record is its technology), then one
  transaction for every row, or nothing.
- RCA Data (``RcaEditor``): the register's own rules; the model is validated and saved row by row.

Shared conversion rules: a value is converted with the model field's own type (text trimmed, numbers, ISO dates,
Yes/No); a blank number or date is NULL (not reported), never 0.
"""
from __future__ import annotations

import math
from datetime import date, datetime

from django.db import models
from django.utils import timezone

from apps.rca.models import RcaEvent, RcaRecord
from apps.sitedata import rules
from apps.sitedata.models import DailySitePerformance, Site, SiteManualOverride


class EditError(Exception):
    """Field errors of one row: {column key: message}."""

    def __init__(self, errors: dict[str, str]):
        super().__init__('; '.join(f'{k}: {v}' for k, v in errors.items()))
        self.errors = errors


class Context:
    """One save: the user and the dataset."""

    def __init__(self, user, dataset_label: str, request=None):
        self.user, self.label = user, dataset_label
        self.request = request
        self.effective_dates_changed = False


def convert(field: models.Field, raw):
    """A cell value as the model field's type. Raises ValueError with a readable message."""
    text = '' if raw is None else str(raw).strip()
    if isinstance(field, models.BooleanField):
        if text.casefold() in ('yes', 'true', '1', 'y'):
            return True
        if text.casefold() in ('no', 'false', '0', 'n'):
            return False
        if not text and field.null:
            return None
        raise ValueError('Enter Yes or No.')
    if isinstance(field, (models.FloatField, models.IntegerField)):
        if not text:
            if field.null:
                return None
            raise ValueError('Enter a number.')
        try:
            number = float(text.replace(',', ''))
        except ValueError as exc:
            raise ValueError('Enter a number.') from exc
        if not math.isfinite(number):
            raise ValueError('Enter a number.')
        if isinstance(field, models.IntegerField):
            if number != int(number):
                raise ValueError('Enter a whole number.')
            return int(number)
        return number
    if isinstance(field, models.DateField):
        if not text:
            if field.null:
                return None
            raise ValueError('Enter a date.')
        try:
            return date.fromisoformat(text[:10])
        except ValueError as exc:
            raise ValueError('Enter the date as YYYY-MM-DD.') from exc
    if field.max_length and len(text) > field.max_length:
        raise ValueError(f'At most {field.max_length} characters.')
    return text


class Editor:
    model: type[models.Model]
    # Column key -> model field name, for the cells that can be changed on existing rows.
    fields: dict[str, str] = {}
    # Extra column keys needed (and allowed) only when adding a row, e.g. the site of a daily value.
    identity: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    contacts: frozenset[str] = frozenset()  # contact columns: Admins only (as for viewing)
    unique_key = '_row'  # the cell a duplicate-identity error is shown on

    def editable(self, admin: bool) -> list[str]:
        return [k for k in self.fields if admin or k not in self.contacts]

    def addable(self, admin: bool) -> list[str]:
        return list(dict.fromkeys([*self.identity, *self.editable(admin)]))

    def pair(self, obj) -> tuple[str, str]:
        return obj.project, obj.circle

    def new(self, ctx: Context):
        return self.model()

    def assign(self, obj, values: dict, ctx: Context, adding: bool) -> list[str]:
        """Set the changed fields; returns the model fields changed. Raises EditError."""
        errors, changed = {}, []
        for key, raw in values.items():
            name = self.fields[key]
            try:
                value = convert(self.model._meta.get_field(name), raw)
            except ValueError as exc:
                errors[key] = str(exc)
                continue
            if adding or getattr(obj, name) != value:
                setattr(obj, name, value)
                changed.append(name)
        if errors:
            raise EditError(errors)
        return changed

    def finish(self, obj, changed: list[str], ctx: Context, adding: bool) -> None:
        """Derived fields and provenance, before validation and save."""

    def after_save(self, obj, before: dict, ctx: Context, adding: bool) -> None:
        """History records of the dataset (after the row is saved)."""


class DailyEditor(Editor):
    """Daily Performance: authorized corrections of sitedata.DailySitePerformance (editing.save, with a reason).

    A change gives the new value of a stored site-day; an addition names a dashboard site (Site ID; Project and
    Circle, when given, must be the site's) and a date without a value. Either availability % or outage minutes is
    given; the other follows by the shared rules. A value is never removed (a missing value is "not reported")."""
    model = DailySitePerformance
    corrections = True  # saved through apps.sitedata.daily, with a reason
    VALUES = ('availability_pct', 'outage_minutes')
    fields = {'availability_pct': 'availability_pct', 'outage_minutes': 'outage_minutes'}
    identity = ('project', 'circle', 'site_id', 'date')
    required = ('site_id', 'date')
    unique_key = 'date'

    def addable(self, admin):
        return [*self.identity, *self.VALUES]

    def pair(self, obj):
        return obj.technology, obj.circle

    def availability(self, values: dict) -> float:
        """The availability % of a row from its availability or outage cell. Raises EditError."""
        text = {k: '' if values.get(k) is None else str(values.get(k)).strip() for k in self.VALUES}
        if not any(text.values()):
            raise EditError({'availability_pct': 'Enter the availability % or the outage minutes (a value cannot be removed).'})
        errors, parsed = {}, {}
        if text['availability_pct']:
            checked = rules.check_availability(text['availability_pct'])
            if checked.usable:
                parsed['availability_pct'] = checked.value
            else:
                errors['availability_pct'] = ('Availability is between 0 and 100%.' if checked.code == 'availability_out_of_range'
                                              else 'Enter a number.')
        if text['outage_minutes']:
            checked = rules.check_outage(text['outage_minutes'])
            if checked.usable:
                parsed['outage_minutes'] = checked.value
            else:
                errors['outage_minutes'] = ('Outage minutes are between 0 and 1,440 per day.' if checked.code == 'outage_out_of_range'
                                            else 'Enter a number.')
        if errors:
            raise EditError(errors)
        if 'availability_pct' in parsed:
            if 'outage_minutes' in parsed and abs(rules.availability_from_outage(parsed['outage_minutes']) - parsed['availability_pct']) > 1e-6:
                raise EditError({'outage_minutes': 'Availability and outage minutes disagree: give one of them.'})
            return parsed['availability_pct']
        return rules.availability_from_outage(parsed['outage_minutes'])

    def site(self, values: dict) -> Site:
        """The dashboard site of a new row. Raises EditError."""
        from apps.sitedata.identifiers import key_of
        sid = str(values.get('site_id') or '').strip()
        site = Site.objects.filter(site_key=key_of(sid)).first()
        if site is None:
            raise EditError({'site_id': f'{sid} is not a Site Master site.'})
        if site.reporting_scope != Site.Scope.DASHBOARD:
            raise EditError({'site_id': f'{site.bsnl_site_id} is outside the dashboard reporting scope.'})
        errors = {}
        project, circle = str(values.get('project') or '').strip(), str(values.get('circle') or '').strip()
        if project and project.casefold() != site.technology.casefold():
            errors['project'] = f'{site.bsnl_site_id} is a {site.technology} site.'
        if circle and circle.upper() != site.circle:
            errors['circle'] = f'{site.bsnl_site_id} is a site of circle {site.circle}.'
        if errors:
            raise EditError(errors)
        return site

    def report_date(self, values: dict) -> date:
        try:
            day = convert(DailySitePerformance._meta.get_field('report_date'), values.get('date'))
        except ValueError as exc:
            raise EditError({'date': str(exc)}) from exc
        if day > timezone.localdate():
            raise EditError({'date': 'A future date cannot have a value.'})
        return day


class SiteEditor(Editor):
    """Safe field edits on existing Site rows; matrix values remain available as explicit fallbacks."""
    model = Site
    fields = {
        'site_name': 'site_name', 'site_type': 'site_type', 'village_code': 'village_code',
        'ba': 'ba', 'oa': 'oa', 'district': 'district', 'sub_district': 'sub_district',
        'site_address': 'site_address', 'commissioning_status': 'commissioning_status',
        'commissioning_date': 'commissioning_date', 'om_status': 'om_status', 'om_start_date': 'om_start_date',
        'on_air_status': 'on_air_status', 'on_air': 'on_air', 'on_air_date': 'on_air_date',
        'latitude': 'latitude', 'longitude': 'longitude', 'eb_status': 'eb_status', 'dg_status': 'dg_status',
        'remarks': 'remarks', 'ci_name': 'ci_name', 'ci_contact': 'ci_contact', 'ie_name': 'ie_name', 'ie_contact': 'ie_contact',
    }
    contacts = frozenset({'ci_contact', 'ie_contact'})
    choice_fields = {'oa': 'oa', 'om_status': 'om_status', 'on_air_status': 'on_air_status'}
    identity = ()
    required = ()
    DATE_RAW = {'commissioning_date': 'commissioning_raw', 'om_start_date': 'om_start_raw', 'on_air_date': 'on_air_raw'}
    EFFECTIVE_DATES = frozenset({'om_start_date', 'on_air_date'})

    def addable(self, admin):
        return []

    def pair(self, obj):
        return obj.technology, obj.circle

    def finish(self, obj, changed, ctx, adding):
        if 'on_air' in changed:
            obj.on_air_status = 'Yes' if obj.on_air else 'No'
            if 'on_air_status' not in changed:
                changed.append('on_air_status')
        for date_field, raw_field in self.DATE_RAW.items():
            if date_field in changed:
                value = getattr(obj, date_field)
                setattr(obj, raw_field, value.isoformat() if value else '')
                if raw_field not in changed:
                    changed.append(raw_field)
        self.sync(obj)

    @staticmethod
    def sync(obj):
        obj.on_air = (obj.on_air_status or '').strip().casefold() == 'yes'
        if obj.reporting_scope == Site.Scope.DASHBOARD:
            obj.om_start_date_issue = rules.om_start_date_issue(obj.om_start_date, obj.om_start_raw or '')
            obj.on_air_date_issue = rules.date_issue(obj.on_air_date, obj.on_air_raw or '')
        else:
            obj.om_start_date_issue = ''
            obj.on_air_date_issue = ''

    def after_save(self, obj, before, ctx, adding):
        changed = {field for field in set(self.fields.values()) | set(self.DATE_RAW.values())
                   if field in before and before[field] != getattr(obj, field)}
        raw_fields = set(self.DATE_RAW.values())

        def persist(field, force=False):
            current = _json_value(getattr(obj, field))
            override = SiteManualOverride.objects.filter(site=obj, field=field).first()
            matrix_value = override.matrix_value if override else _json_value(before.get(field))
            if current == matrix_value and not force:
                if override:
                    override.delete()
                return
            if override:
                override.updated_by = ctx.user
                override.save(update_fields=['updated_by', 'updated_at'])
            else:
                SiteManualOverride.objects.create(site=obj, field=field, matrix_value=matrix_value, updated_by=ctx.user)

        for field in changed - raw_fields - {'on_air'}:
            persist(field)
        for date_field, raw_field in self.DATE_RAW.items():
            if date_field in changed:
                has_date_override = SiteManualOverride.objects.filter(site=obj, field=date_field).exists()
                persist(raw_field, force=has_date_override)
        if any(field in self.EFFECTIVE_DATES for field in before if before.get(field) != getattr(obj, field)):
            ctx.effective_dates_changed = True


class EscalationEditor(SiteEditor):
    """Editable Consolidation/Escalation attributes, with Site identity and reporting scope kept immutable."""
    fields = {
        'site_name': 'site_name', 'site_type': 'site_type', 'village_code': 'village_code',
        'ba': 'ba', 'oa': 'oa', 'district': 'district', 'sub_district': 'sub_district',
        'site_address': 'site_address', 'commissioning_status': 'commissioning_status',
        'commissioning_date': 'commissioning_date', 'om_status': 'om_status', 'om_start_date': 'om_start_date',
        'on_air_status': 'on_air_status', 'on_air_date': 'on_air_date', 'eb_status': 'eb_status',
        'dg_status': 'dg_status', 'case_type': 'case_type',
        'ci_emp_code': 'ci_emp_code', 'ci_name': 'ci_name', 'ci_contact': 'ci_contact',
        'ie_emp_code': 'ie_emp_code', 'ie_name': 'ie_name', 'ie_contact': 'ie_contact',
        'il_emp_code': 'il_emp_code', 'il_name': 'il_name', 'il_contact': 'il_contact',
        'om_manager_emp_code': 'om_manager_emp_code', 'om_manager_name': 'om_manager_name',
        'om_manager_contact': 'om_manager_contact', 'cbh_name': 'cbh_name', 'cbh_contact': 'cbh_contact',
        'ct_status': 'ct_status', 'ct_name': 'ct_name', 'ct_contact': 'ct_contact',
        'rigger_emp_code': 'rigger_emp_code', 'rigger_name': 'rigger_name', 'rigger_contact': 'rigger_contact',
        'latitude': 'latitude', 'longitude': 'longitude', 'smps_make': 'smps_make', 'remarks': 'remarks',
    }
    contacts = frozenset({
        'ci_contact', 'ie_contact', 'il_contact', 'om_manager_contact', 'cbh_contact', 'ct_contact', 'rigger_contact',
    })
    choice_fields = {
        **SiteEditor.choice_fields,
        'commissioning_status': 'commissioning_status', 'eb_status': 'eb_status', 'dg_status': 'dg_status',
        'ct_status': 'ct_status',
    }


class RcaEditor(Editor):
    """RCA Data: the register's own rules (apps.rca.views._manual_fields) for keys, dates, project and circle."""
    model = RcaRecord
    fields = {k: k for k in ('reporting_date', 'project', 'circle', 'site_id', 'site_name', 'oa', 'ba', 'om_start_raw', 'outage_minutes',
                             'final_bucket', 'bucket_2', 'rca_text')}
    required = ('reporting_date', 'project', 'circle', 'site_id', 'rca_text')
    TRACKED = ('reporting_date', 'project', 'circle', 'site_id', 'site_name', 'oa', 'ba', 'om_start_raw', 'outage_minutes',
               'final_bucket', 'bucket_2', 'rca_text')

    def new(self, ctx):
        return RcaRecord(source=RcaRecord.Source.MANUAL, created_by=ctx.user)

    def assign(self, obj, values, ctx, adding):
        from rest_framework.exceptions import ValidationError

        from apps.rca.views import _manual_fields
        current = {k: getattr(obj, k) for k in self.TRACKED} if not adding else {}
        merged = {**{k: (v.isoformat() if isinstance(v, date) else v) for k, v in current.items()}, **values}
        try:
            fields = _manual_fields(merged)
        except ValidationError as exc:
            # On an existing record, only the cells being changed must pass (older imports may lack e.g. an RCA text).
            detail = {k: str(v[0] if isinstance(v, list) else v) for k, v in exc.detail.items()}
            relevant = detail if adding else {k: v for k, v in detail.items() if k in values}
            if relevant:
                raise EditError(relevant) from exc
            fields = None
        if fields is None:  # only pre-existing problems: apply the changed cells as given
            fields = {}
            for key in values:
                fields[key] = convert(self.model._meta.get_field(key), values[key])
        changed = []
        for name, value in fields.items():
            if name in ('project_raw', 'circle_raw') and not adding:
                continue  # an import's source spelling is kept
            if adding or getattr(obj, name) != value:
                setattr(obj, name, value)
                changed.append(name)
        return changed

    def finish(self, obj, changed, ctx, adding):
        """Matching keys always follow the text (also when an older record bypassed the full rules)."""
        from apps.rca.parser import site_key as rca_site_key
        from apps.rca.parser import text_key
        obj.site_key = rca_site_key(obj.site_id)
        obj.final_bucket_key, obj.bucket_2_key, obj.rca_key = text_key(obj.final_bucket), text_key(obj.bucket_2), text_key(obj.rca_text)
        if 'om_start_raw' in changed:
            obj.om_start = {'yes': True, 'no': False}.get((obj.om_start_raw or '').casefold())

    def after_save(self, obj, before, ctx, adding):
        if adding:
            RcaEvent.objects.create(record=obj, user=ctx.user, action='recorded', changes={'via': 'Data Panel'})
        else:
            diff = {k: {'from': _plain(before.get(k)), 'to': _plain(getattr(obj, k))} for k in self.TRACKED if before.get(k) != getattr(obj, k)}
            if diff:
                RcaEvent.objects.create(record=obj, user=ctx.user, action='record_edited', changes={**diff, 'via': 'Data Panel'})


def _plain(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def _json_value(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


# Datasets without an editor are read-only (View / Export).
EDITORS: dict[str, Editor] = {
    'uptime_sites': SiteEditor(),
    'uptime_daily': DailyEditor(),
    'escalation': EscalationEditor(),
    'rca': RcaEditor(),
}

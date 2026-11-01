"""Data Panel editing: how each dataset's cells map to its PostgreSQL model, and the rules a change must follow.

One ``Editor`` per dataset of ``datasets.DATASETS`` (``EDITORS``). The save itself is generic (``editing.save``): it
checks permissions and project/circle scope, applies the editor, validates the model (field types, lengths, unique
constraints), and writes everything in one transaction or nothing. A dataset without an editor stays read-only.

To make a new dataset editable: register it in ``DATASETS`` and add an ``Editor`` here naming its editable columns
(and identity columns for Add). Its View / Add / Edit / Export permissions appear on Users & Roles automatically.
Nothing here deletes a record.

Rules shared by every editor:
- A value is converted with the model field's own type (text trimmed, numbers, ISO dates, Yes/No); a blank number or
  date is NULL (not reported), never 0.
- Derived columns are recomputed as the importers do (site keys, On-Air / O&M Start flags, RCA matching keys).
- Project and circle must form an Organization association when they are set or changed.
- Rows written by a save point to that save's own import batch (kind "Data Panel edit"), so every value still traces
  back to where it came from, and the dashboard's database cache refreshes.
"""
from __future__ import annotations

import math
from datetime import date, datetime

from django.db import models
from django.utils import timezone

from apps.rca.models import RcaEvent, RcaRecord
from apps.uptimedb.models import (DataImportBatch, EscalationImportBatch, EscalationSite, SiteDailyPerformance, SiteMonthlyPerformance,
                                  UptimeSite)
from apps.uptimedb.parser import site_key


class EditError(Exception):
    """Field errors of one row: {column key: message}."""

    def __init__(self, errors: dict[str, str]):
        super().__init__('; '.join(f'{k}: {v}' for k, v in errors.items()))
        self.errors = errors


class Context:
    """One save: the user, and the provenance batches created on first use."""

    def __init__(self, user, dataset_label: str):
        self.user, self.label = user, dataset_label
        self._uptime_batch = self._escalation_batch = None
        self.relink = False

    def uptime_batch(self) -> DataImportBatch:
        if self._uptime_batch is None:
            now = timezone.now()
            self._uptime_batch = DataImportBatch.objects.create(
                kind=DataImportBatch.Kind.DATA_PANEL, status=DataImportBatch.Status.COMMITTED, committed_at=now,
                original_filename='Data Panel edit', checksum_sha256='data-panel', sheet_name=self.label[:64], stored_path='-',
                imported_by=self.user, initiated_via='data_panel', remarks=f'Changed in the Data Panel ({self.label}).')
        return self._uptime_batch

    def escalation_batch(self) -> EscalationImportBatch:
        if self._escalation_batch is None:
            self._escalation_batch = EscalationImportBatch.objects.create(
                original_filename='Data Panel edit', checksum_sha256='data-panel', sheet_name=self.label[:64], stored_path='-',
                status=EscalationImportBatch.Status.COMMITTED, committed_at=timezone.now(), imported_by=self.user, initiated_via='data_panel')
        return self._escalation_batch


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


def _association(project: str, circle: str) -> str | None:
    from apps.organization.services import is_associated
    return None if is_associated(project, circle, active_only=False) else f'{circle} is not a circle of {project} (Administration › Organization).'


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


class _SiteIdentity(Editor):
    """Project, circle and site ID with the site key and the association rule (Site Master, Escalation Matrix)."""
    unique_key = 'site_id'

    def finish(self, obj, changed, ctx, adding):
        if 'circle' in changed:
            obj.circle = obj.circle.upper()  # circle codes are stored upper case
        if 'site_id' in changed:
            obj.site_key = site_key(obj.site_id)
        if adding or {'project', 'circle'} & set(changed):
            problem = _association(obj.project, obj.circle)
            if problem:
                raise EditError({'circle': problem})
            ctx.relink = True
        if 'site_id' in changed:
            ctx.relink = True


class SiteMasterEditor(_SiteIdentity):
    model = UptimeSite
    fields = {k: k for k in ('project', 'circle', 'site_id', 'site_name', 'oa', 'ba', 'on_air', 'eb', 'od_eb_working_status',
                             'solar_logic_done', 'ie_name', 'ie_contact', 'ci_name', 'ci_contact')}
    required = ('project', 'circle', 'site_id')
    contacts = frozenset({'ie_contact', 'ci_contact'})

    def new(self, ctx):
        return UptimeSite(source_file='Data Panel', source_row=0)

    def finish(self, obj, changed, ctx, adding):
        super().finish(obj, changed, ctx, adding)
        if adding:
            obj.project_raw, obj.circle_raw = obj.project, obj.circle
        if 'on_air' in changed:  # the flag and its "as written" value stay consistent, as the importer reads them
            obj.on_air_raw = 'Yes' if obj.on_air else 'No'
        obj.batch = ctx.uptime_batch()


class _SitePerformance(Editor):
    """Daily / monthly values of one Site Master site: the site is chosen by project, circle and site ID when adding."""
    identity = ('project', 'circle', 'site_id')
    period: str = ''  # the date / month column: set when adding, fixed afterwards

    @property
    def unique_key(self):
        return self.period

    def addable(self, admin):
        return [*self.identity, self.period, *self.editable(admin)]

    def pair(self, obj):
        return obj.site.project, obj.site.circle

    def assign(self, obj, values, ctx, adding):
        values = dict(values)
        site_values = {k: values.pop(k, None) for k in self.identity}
        errors = {}
        if adding:
            project, circle, sid = (str(site_values[k] or '').strip() for k in self.identity)
            if not (project and circle and sid):
                errors.update({k: 'Required.' for k in self.identity if not str(site_values[k] or '').strip()})
            else:
                site = UptimeSite.objects.filter(project=project, circle=circle.upper(), site_key=site_key(sid)).first()
                if site is None:
                    errors['site_id'] = f'{sid} is not a Site Master site of {project} {circle.upper()}.'
                else:
                    obj.site = site
        try:
            changed = super().assign(obj, values, ctx, adding)
        except EditError as exc:
            raise EditError({**errors, **exc.errors}) from exc
        if errors:
            raise EditError(errors)
        return changed

    def finish(self, obj, changed, ctx, adding):
        obj.batch = ctx.uptime_batch()


class DailyEditor(_SitePerformance):
    model = SiteDailyPerformance
    period = 'date'
    fields = {'date': 'date', 'uptime_pct': 'uptime_pct', 'outage_minutes': 'outage_minutes'}
    required = ('project', 'circle', 'site_id', 'date')

    def editable(self, admin):
        return ['uptime_pct', 'outage_minutes']  # the site and date identify the value

    def finish(self, obj, changed, ctx, adding):
        if obj.outage_minutes is not None and not 0 <= obj.outage_minutes <= 1440:
            raise EditError({'outage_minutes': 'Outage minutes are between 0 and 1,440 per day.'})
        if obj.uptime_pct is not None and not 0 <= obj.uptime_pct <= 100:
            raise EditError({'uptime_pct': 'Availability is between 0 and 100%.'})
        super().finish(obj, changed, ctx, adding)


class MonthlyEditor(_SitePerformance):
    model = SiteMonthlyPerformance
    period = 'month'
    fields = {'month': 'month', 'uptime_pct': 'uptime_pct', 'outage_minutes': 'outage_minutes', 'bucket': 'bucket', 'ff_count': 'ff_count',
              'om_start_raw': 'om_start_raw'}
    required = ('project', 'circle', 'site_id', 'month')

    def editable(self, admin):
        return ['uptime_pct', 'outage_minutes', 'bucket', 'ff_count', 'om_start_raw']

    def finish(self, obj, changed, ctx, adding):
        if 'month' in changed and obj.month and obj.month.day != 1:
            raise EditError({'month': 'Give the first day of the month (YYYY-MM-01).'})
        if obj.uptime_pct is not None and not 0 <= obj.uptime_pct <= 100:
            raise EditError({'uptime_pct': 'Availability is between 0 and 100%.'})
        if obj.outage_minutes is not None and obj.outage_minutes < 0:
            raise EditError({'outage_minutes': 'Outage minutes cannot be negative.'})
        if 'om_start_raw' in changed:  # as the importer: "Yes" is O&M started; blank keeps "not recorded"
            obj.om_start = obj.om_start_raw.casefold() == 'yes' if obj.om_start_raw else None
        super().finish(obj, changed, ctx, adding)


class EscalationEditor(_SiteIdentity):
    model = EscalationSite
    fields = {k: k for k in (
        'project', 'circle', 'site_id', 'site_name', 'site_type', 'ba', 'oa', 'district', 'sub_district', 'village_code', 'commissioning_date',
        'commissioning_status', 'on_air_status', 'on_air_date', 'om_status', 'om_start_date', 'eb_status', 'dg_status', 'case_type',
        'ci_emp_code', 'ci_name', 'ci_contact', 'ie_emp_code', 'ie_name', 'ie_contact', 'il_name', 'il_contact', 'om_manager_name',
        'om_manager_contact', 'cbh_name', 'cbh_contact', 'ct_status', 'ct_name', 'ct_contact', 'rigger_name', 'rigger_contact',
        'latitude', 'longitude', 'site_address', 'smps_make', 'bts_id_b1', 'bts_id_b28', 'master_bts_id', 'remarks')}
    required = ('project', 'circle', 'site_id')
    contacts = frozenset(k for k in fields if k.endswith('_contact'))
    RAW_DATES = {'commissioning_date': 'commissioning_raw', 'on_air_date': 'on_air_raw', 'om_start_date': 'om_start_raw'}

    def new(self, ctx):
        return EscalationSite(source_file='Data Panel', source_row=0)

    def finish(self, obj, changed, ctx, adding):
        super().finish(obj, changed, ctx, adding)
        if adding:
            obj.entity_raw, obj.circle_raw = obj.project, obj.circle
        for name, raw in self.RAW_DATES.items():  # the "as written" text follows a changed date
            if name in changed:
                setattr(obj, raw, getattr(obj, name).isoformat() if getattr(obj, name) else '')
        obj.batch = ctx.escalation_batch()


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


EDITORS: dict[str, Editor] = {
    'uptime_sites': SiteMasterEditor(),
    'uptime_daily': DailyEditor(),
    'uptime_monthly': MonthlyEditor(),
    'escalation': EscalationEditor(),
    'rca': RcaEditor(),
}

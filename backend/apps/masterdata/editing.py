"""Data Panel save: every pending change of one dataset, validated and written in one transaction, or nothing.

Payload: {"changes": [{"id": 12, "values": {...}}], "additions": [{"values": {...}}], "reason": "..."}.
Checks, in order, all on the server: the dataset has an editor (otherwise it is read-only); the dataset's Edit / Add
permission; the row is inside the user's project/circle scope for that permission (accounts.access); only editable
columns; the editor's rules. Any error rolls the whole save back and is returned against its row and cell. There is
no delete: rows missing from the payload are left as they are.

Site Master and Escalation Matrix (editors.SiteEditor / EscalationEditor): only dataset-specific non-identity fields may
change; each manual value has a persisted matrix baseline and is kept across imports until explicitly reverted.
Effective-date changes refresh monthly results.
Daily Performance (editors.DailyEditor): a reason is required for the save; each changed value is an authorized
correction (apps.sitedata.daily.correct) and each added site-day an authorized value (daily.add_correction), all in
one transaction; the monthly results and the dashboard cache are refreshed once afterwards. A finalized month is
refused (daily.FinalizedPeriod).
RCA Data: the model's own validation (types, lengths, unique constraints) row by row, then saved.
"""
from __future__ import annotations

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction

from apps.accounts.access import can, pairs_for, pairs_q
from apps.accounts.catalog import data_module
from apps.accounts.roles import ADMIN, role_of

from .datasets import Dataset
from .editors import EDITORS, Context, DailyEditor, EditError, SiteEditor

MAX_ROWS = 500
TOLERANCE = 1e-6  # percentage points: the same value (apps.sitedata.daily.TOLERANCE)


class SaveRefused(Exception):
    def __init__(self, status: int, message: str, details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.details = details or {}


class _Rollback(Exception):
    pass


def capabilities(user, ds: Dataset) -> dict:
    """What the Data Panel may offer this user on this dataset (the save checks again). Read-only datasets (no editor)
    never offer Edit or Add, whatever the role grants."""
    module, editor, admin = data_module(ds.key), EDITORS.get(ds.key), role_of(user) == ADMIN
    allowed = {a: can(user, module, a) for a in ('view', 'create', 'edit', 'export')}
    return {
        'view': allowed['view'], 'export': allowed['export'],
        'edit': bool(editor and editor.fields) and allowed['edit'], 'add': bool(editor and editor.addable(admin)) and allowed['create'],
        'editable': editor.editable(admin) if editor and allowed['edit'] else [],
        'addable': editor.addable(admin) if editor and allowed['create'] else [],
        'required': list(editor.required) if editor else [],
        'reason_required': bool(getattr(editor, 'corrections', False)),
    }


def _field_errors(editor, exc: ModelValidationError) -> dict[str, str]:
    reverse = {name: key for key, name in editor.fields.items()}
    derived = {'site_key': 'site_id', 'site': 'site_id', 'rca_key': 'rca_text', 'final_bucket_key': 'final_bucket', 'bucket_2_key': 'bucket_2'}
    out = {}
    for name, messages in exc.message_dict.items():
        key = reverse.get(name) or derived.get(name) or '_row'
        text = ' '.join(messages)
        if 'already exists' in text or 'constraint' in text.casefold():
            text = 'A record with the same identity already exists (each must be unique).'
            if key == '_row':
                key = editor.unique_key
        out[key] = text
    return out


def _in_scope(pairs, pair) -> bool:
    return pairs is None or pair in pairs


def _snapshot(obj) -> dict:
    return {f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields}


def _unknown(values: dict, allowed) -> None:
    unknown = sorted(set(values) - set(allowed))
    if unknown:
        raise EditError({k: 'This column cannot be changed here.' for k in unknown})


def save(user, ds: Dataset, payload, request=None) -> dict:
    editor = EDITORS.get(ds.key)
    if editor is None:
        raise SaveRefused(400, f'{ds.label} is read-only.')
    changes, additions = payload.get('changes') or [], payload.get('additions') or []
    if not isinstance(changes, list) or not isinstance(additions, list):
        raise SaveRefused(400, 'Give lists of changes and additions.')
    if len(changes) + len(additions) > MAX_ROWS:
        raise SaveRefused(400, f'Save at most {MAX_ROWS} rows at a time.')
    module = data_module(ds.key)
    if changes and not can(user, module, 'edit'):
        raise SaveRefused(403, f'You do not have the Edit permission on {ds.label}.')
    if additions and not can(user, module, 'create'):
        raise SaveRefused(403, f'You do not have the Add permission on {ds.label}.')
    if isinstance(editor, DailyEditor):
        return _save_corrections(user, ds, editor, changes, additions, payload.get('reason'), request)
    return _save_rows(user, ds, editor, changes, additions, request)


def _save_corrections(user, ds: Dataset, editor: DailyEditor, changes: list, additions: list, reason, request) -> dict:
    """Daily Performance: authorized corrections, all or none, then one refresh of the monthly results and caches."""
    from apps.sitedata import daily
    from apps.sitedata.uploads import refresh_after_daily_write
    reason = reason.strip() if isinstance(reason, str) else ''
    if not reason:
        raise SaveRefused(400, 'Give the reason for this correction (it is kept with every changed value).', {'reason': 'Required.'})
    admin = role_of(user) == ADMIN
    module = data_module(ds.key)
    edit_pairs, add_pairs = pairs_for(user, module, 'edit'), pairs_for(user, module, 'create')
    errors: dict[str, dict] = {'changes': {}, 'additions': {}}
    done = {'updated': 0, 'added': 0, 'ids': []}
    dates = set()

    def problem(exc) -> dict:
        if isinstance(exc, EditError):
            return exc.errors
        if isinstance(exc, daily.FinalizedPeriod):
            return {'_row': f'{exc} The month is finalized: its values cannot be changed here.'}
        return {'_row': str(exc)}

    failures = (EditError, daily.FinalizedPeriod, ValueError, DjangoPermissionDenied)
    try:
        with transaction.atomic():
            scope = ds.queryset().filter(pairs_q(edit_pairs, ds.project, ds.circle))
            for i, item in enumerate(changes):
                key = str(item.get('id')) if isinstance(item, dict) else str(i)
                values = item.get('values') if isinstance(item, dict) else None
                record = scope.filter(pk=item.get('id')).first() if isinstance(item, dict) and str(item.get('id', '')).isdigit() else None
                if record is None or not isinstance(values, dict):
                    errors['changes'][key] = {'_row': 'This record does not exist or is outside the projects and circles you may change.'}
                    continue
                try:
                    _unknown(values, editor.editable(admin))
                    value = editor.availability(values)
                    if abs(value - record.availability_pct) <= TOLERANCE:
                        continue  # the stored value: nothing to correct
                    daily.correct(record, value, user=user, reason=reason, request=request, authorized=True, refresh=False)
                except failures as exc:
                    errors['changes'][key] = problem(exc)
                    continue
                done['updated'] += 1
                done['ids'].append(record.pk)
                dates.add(record.report_date)
            for i, item in enumerate(additions):
                values = item.get('values') if isinstance(item, dict) else None
                if not isinstance(values, dict):
                    errors['additions'][str(i)] = {'_row': 'Give the values of the new record.'}
                    continue
                try:
                    _unknown(values, editor.addable(admin))
                    missing = [k for k in editor.required if not str(values.get(k) or '').strip()]
                    if missing:
                        raise EditError({k: 'Required.' for k in missing})
                    site = editor.site(values)
                    day = editor.report_date(values)
                    if not _in_scope(add_pairs, (site.technology, site.circle)):
                        raise EditError({'circle': 'Outside the projects and circles you may change.'})
                    value = editor.availability(values)
                    record = daily.add_correction(site, day, value, user=user, reason=reason, request=request, authorized=True, refresh=False)
                except failures as exc:
                    errors['additions'][str(i)] = problem(exc)
                    continue
                done['added'] += 1
                done['ids'].append(record.pk)
                dates.add(day)
            if errors['changes'] or errors['additions']:
                raise _Rollback()
    except _Rollback:
        return {'saved': False, 'errors': errors}
    except IntegrityError as exc:
        return {'saved': False, 'errors': {'changes': {}, 'additions': {}, '_form': f'The database refused the changes: {str(exc).splitlines()[0][:200]}'}}
    if dates:
        refresh_after_daily_write(sorted(dates), request)  # monthly results and the dashboard read the corrected values
    return {'saved': True, **done}


def _save_rows(user, ds: Dataset, editor, changes: list, additions: list, request=None) -> dict:
    """Model-backed editors (RCA Data): assign, validate and save each row."""
    module, admin = data_module(ds.key), role_of(user) == ADMIN
    edit_pairs, add_pairs = pairs_for(user, module, 'edit'), pairs_for(user, module, 'create')
    errors: dict[str, dict] = {'changes': {}, 'additions': {}}
    ctx = Context(user, ds.label, request)
    done = {'updated': 0, 'added': 0, 'ids': []}

    def write(obj, values, allowed, adding, pairs, before):
        _unknown(values, allowed)
        if adding:
            missing = [k for k in editor.required if not str(values.get(k) or '').strip()]
            if missing:
                raise EditError({k: 'Required.' for k in missing})
        changed = editor.assign(obj, values, ctx, adding)
        if not changed and not adding:
            return False
        editor.finish(obj, changed, ctx, adding)
        if not _in_scope(pairs, editor.pair(obj)):
            raise EditError({'circle': 'Outside the projects and circles you may change.'})
        after = _snapshot(obj)
        touched = {name for name, value in after.items() if adding or before.get(name) != value}
        exclude = [] if adding else [f.name for f in obj._meta.concrete_fields if f.attname not in touched]
        # NULL is "not reported" where the database allows it (some nullable fields lack blank=True, a form-only flag).
        exclude += [f.name for f in obj._meta.concrete_fields if f.null and getattr(obj, f.attname) is None and f.name not in exclude]
        try:
            obj.full_clean(exclude=exclude)
        except ModelValidationError as exc:
            raise EditError(_field_errors(editor, exc)) from exc
        obj.save()
        editor.after_save(obj, before, ctx, adding)
        return True

    try:
        with transaction.atomic():
            if isinstance(editor, SiteEditor):
                from apps.sitedata.uploads import write_lock
                write_lock()
            scope = ds.queryset().filter(pairs_q(edit_pairs, ds.project, ds.circle))
            for i, item in enumerate(changes):
                key = str(item.get('id')) if isinstance(item, dict) else str(i)
                values = item.get('values') if isinstance(item, dict) else None
                obj = scope.filter(pk=item.get('id')).select_for_update(of=('self',)).first() if isinstance(item, dict) and str(item.get('id', '')).isdigit() else None
                if obj is None or not isinstance(values, dict):
                    errors['changes'][key] = {'_row': 'This record does not exist or is outside the projects and circles you may change.'}
                    continue
                expected = item.get('updated_at')
                current_version = getattr(obj, 'updated_at', None)
                if expected is not None and (not isinstance(expected, str) or current_version is None or current_version.isoformat() != expected):
                    errors['changes'][key] = {'_row': 'This record changed after it was loaded. Reload it and reapply your edit.'}
                    continue
                before = _snapshot(obj)
                try:
                    if write(obj, values, editor.editable(admin), False, edit_pairs, before):
                        done['updated'] += 1
                        done['ids'].append(obj.pk)
                except EditError as exc:
                    errors['changes'][key] = exc.errors
            for i, item in enumerate(additions):
                values = item.get('values') if isinstance(item, dict) else None
                if not isinstance(values, dict):
                    errors['additions'][str(i)] = {'_row': 'Give the values of the new record.'}
                    continue
                obj = editor.new(ctx)
                try:
                    write(obj, values, editor.addable(admin), True, add_pairs, {})
                    done['added'] += 1
                    done['ids'].append(obj.pk)
                except EditError as exc:
                    errors['additions'][str(i)] = exc.errors
            if errors['changes'] or errors['additions']:
                raise _Rollback()
    except _Rollback:
        return {'saved': False, 'errors': errors}
    except IntegrityError as exc:
        return {'saved': False, 'errors': {'changes': {}, 'additions': {}, '_form': f'The database refused the changes: {str(exc).splitlines()[0][:200]}'}}
    if ctx.effective_dates_changed:
        from apps.sitedata.models import DailySitePerformance
        from apps.sitedata.uploads import refresh_after_daily_write
        refresh_after_daily_write(DailySitePerformance.objects.dates('report_date', 'month'), request)
    return {'saved': True, **done}

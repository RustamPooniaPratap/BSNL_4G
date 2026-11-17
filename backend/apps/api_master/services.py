"""API Registry review rules: who may change an endpoint's status, and to what."""
from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone

from .models import ApiEndpoint

S = ApiEndpoint.Status
# Allowed transitions. An Approved endpoint is withdrawn by Deprecating it; a decision can be reopened to Pending.
TRANSITIONS = {
    S.PENDING: {S.APPROVED, S.REJECTED},
    S.APPROVED: {S.DEPRECATED, S.PENDING},
    S.REJECTED: {S.PENDING},
    S.DEPRECATED: {S.PENDING},
}


class ReviewError(Exception):
    def __init__(self, message: str, field: str = 'status'):
        super().__init__(message)
        self.field = field


def review(endpoint: ApiEndpoint, *, status: str, note: str, fields_reviewed: bool, user) -> ApiEndpoint:
    """Change the review status. A note is required; blocked endpoints cannot be approved; endpoints whose response holds
    sensitive fields need an explicit confirmation that the fields were reviewed."""
    note = (note or '').strip()
    if status not in S.values:
        raise ReviewError('Choose Pending, Approved, Rejected or Deprecated.')
    if status == endpoint.status:
        raise ReviewError(f'The endpoint is already {endpoint.get_status_display()}.')
    if status not in TRANSITIONS[endpoint.status]:
        allowed = ', '.join(sorted(S(s).label for s in TRANSITIONS[endpoint.status]))
        raise ReviewError(f'{endpoint.get_status_display()} can change to: {allowed}.')
    if not note:
        raise ReviewError('Enter the reason for this decision.', 'note')
    if status == S.APPROVED:
        if endpoint.blocked:
            raise ReviewError(f'This endpoint can never be exposed externally: {endpoint.block_reason}.')
        if not endpoint.present:
            raise ReviewError('This route no longer exists in the portal.')
        if endpoint.method != 'GET':
            raise ReviewError('Only read-only (GET) endpoints can be approved.')
        if endpoint.field_review and not fields_reviewed:
            raise ReviewError(f'Confirm that the response fields were reviewed ({endpoint.field_review}).', 'fields_reviewed')
    endpoint.status, endpoint.review_note = status, note[:2000]
    endpoint.reviewed_by, endpoint.reviewed_at = user, timezone.now()
    endpoint.save(update_fields=['status', 'review_note', 'reviewed_by', 'reviewed_at', 'updated_at'])
    return endpoint


def overview() -> dict:
    """Registry counts from the database (later phases add applications, credentials and requests)."""
    present = ApiEndpoint.objects.filter(present=True)
    raw = present.aggregate(
        n_total=Count('id'), n_approved=Count('id', filter=Q(status=S.APPROVED)), n_pending=Count('id', filter=Q(status=S.PENDING)),
        n_rejected=Count('id', filter=Q(status=S.REJECTED)), n_deprecated=Count('id', filter=Q(status=S.DEPRECATED)),
        n_blocked=Count('id', filter=Q(blocked=True)), n_field_review=Count('id', filter=Q(field_review__gt='')),
        n_reviewable=Count('id', filter=Q(blocked=False)))
    counts = {k.removeprefix('n_'): v for k, v in raw.items()}  # aliases cannot reuse the model's field names
    methods = dict(present.values_list('method').annotate(n=Count('id')).order_by('method'))
    modules = list(present.values('module').annotate(total=Count('id'), approved=Count('id', filter=Q(status=S.APPROVED)),
                                                   blocked=Count('id', filter=Q(blocked=True))).order_by('module'))
    last = ApiEndpoint.objects.order_by('-last_seen').values_list('last_seen', flat=True).first()
    return {**counts, 'no_longer_present': ApiEndpoint.objects.filter(present=False).count(), 'methods': methods,
            'modules': modules, 'last_sync': last.isoformat() if last else None}

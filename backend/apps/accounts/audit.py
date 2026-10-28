"""Audit trail for sign-ins and account administration.

Written to the ``audit`` logger (backend/logs/audit.log by default; see settings). Only
event names, login IDs, user ids and the client address are recorded: never passwords,
temporary passwords, session ids, CSRF tokens or cookies.
"""
import logging

logger = logging.getLogger('audit')


def client_ip(request) -> str:
    # REMOTE_ADDR only: X-Forwarded-For is client-controlled unless a trusted proxy sets it.
    return request.META.get('REMOTE_ADDR', '') if request is not None else ''


def audit(event: str, request=None, **fields) -> None:
    actor = getattr(request, 'user', None) if request is not None else None
    who = actor.get_username() if actor is not None and actor.is_authenticated else '-'
    details = ' '.join(f'{k}={str(v)[:80]!r}' for k, v in sorted(fields.items()))
    logger.info('%s actor=%s ip=%s %s', event, who, client_ip(request), details)

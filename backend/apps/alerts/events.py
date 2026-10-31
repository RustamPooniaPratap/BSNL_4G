"""Real application events that can start an automation. Only upload failures exist in this release."""
import logging

from .models import Automation

logger = logging.getLogger(__name__)


def upload_failed(*, kind: str, batch_id: int, file: str, reason: str, uploader_id: int | None, project: str = '', circle: str = '',
                  date: str = '', status: str = 'Failed') -> None:
    """A raw CSV or RCA upload failed or was rejected: queue each enabled Upload Failure Alert once (the worker sends it).

    Never raises: an alert problem must not change the upload's own outcome.
    """
    from .engine import queue
    label = {'raw_csv': 'Raw daily CSV upload', 'rca': 'RCA upload'}.get(kind, 'Upload')
    try:
        for a in Automation.objects.filter(kind=Automation.Kind.UPLOAD_FAILURE, enabled=True):
            if a.project and project and a.project != project:
                continue
            if a.circles and circle and circle not in a.circles:
                continue
            queue(a, trigger='event', dedupe_key=f'{a.pk}:{kind}:{batch_id}', event={
                'kind': kind, 'label': label, 'batch': batch_id, 'file': file, 'reason': reason[:500], 'uploader_id': uploader_id,
                'project': project, 'circle': circle, 'date': date, 'status': status})
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception('Upload failure alert could not be queued')

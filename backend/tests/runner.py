"""Test runner that isolates tests from the real Data folders.

The active uploaded workbook takes precedence over MASTER_WORKBOOK_PATH, so
without isolation a real upload would leak into every test. Each run gets
empty temporary directories for the workbook store and raw uploads.
"""
import logging
import logging.handlers
import tempfile
from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class IsolatedDataRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        # Remember the real store so reconciliation tests can find an uploaded workbook.
        settings.REAL_WORKBOOK_STORE_DIR = settings.WORKBOOK_STORE_DIR
        self._tmp = tempfile.TemporaryDirectory(prefix='portal-tests-')
        root = Path(self._tmp.name)
        self._override = override_settings(
            WORKBOOK_STORE_DIR=root / 'workbooks',
            RAW_UPLOAD_DIR=root / 'raw',
            MASTER_WORKBOOK_PATH='',
        )
        self._override.enable()
        # Tests must never write to the real audit log (backend/logs/audit.log).
        audit = logging.getLogger('audit')
        self._audit_handlers = audit.handlers[:]
        audit.handlers = [h for h in audit.handlers if not isinstance(h, logging.FileHandler)]
        super().setup_test_environment(**kwargs)

    def teardown_test_environment(self, **kwargs):
        super().teardown_test_environment(**kwargs)
        logging.getLogger('audit').handlers = self._audit_handlers
        self._override.disable()
        self._tmp.cleanup()

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
        # The dashboard pages read the new data layer only (apps.sitedata.dashboard_source.load). Tests that create
        # sitedata records get exactly that; the many API, permission and calculation tests built on a synthetic
        # Master workbook (tests.workbook_factory) get that workbook's dataset through the same single entry point, so
        # they keep testing the endpoints and dashboard.metrics. Test-only: the application has no such fallback.
        from unittest import mock

        from apps.sitedata import dashboard_source
        original = dashboard_source.load

        def load(variant: str = 'all'):
            from apps.sitedata.models import Site
            if Site.objects.exists():
                return original(variant)
            from apps.dashboard.workbook import get_dataset
            return get_dataset()

        self._load_patch = mock.patch.object(dashboard_source, 'load', load)
        self._load_patch.start()
        super().setup_test_environment(**kwargs)

    def teardown_test_environment(self, **kwargs):
        super().teardown_test_environment(**kwargs)
        self._load_patch.stop()
        logging.getLogger('audit').handlers = self._audit_handlers
        self._override.disable()
        self._tmp.cleanup()

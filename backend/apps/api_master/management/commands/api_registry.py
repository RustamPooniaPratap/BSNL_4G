"""API Registry from the command line.

    manage.py api_registry list   # discovered endpoints with their blocked / field-review classification (no database)
    manage.py api_registry sync   # record them in the registry (new ones Pending; review decisions kept)
"""
from collections import Counter

from django.core.management.base import BaseCommand

from apps.api_master import discovery


class Command(BaseCommand):
    help = 'List or synchronise the API Registry with the portal URL configuration.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['list', 'sync'])

    def handle(self, *args, action, **options):
        if action == 'sync':
            result = discovery.sync()
            self.stdout.write(' '.join(f'{k}={v}' for k, v in result.items()))
            return
        found = discovery.discover()
        for f in found:
            flag = f'BLOCKED ({f.block_reason})' if f.blocked else (f'FIELD REVIEW ({f.field_review})' if f.field_review else 'reviewable')
            self.stdout.write(f'{f.method:6} {f.path:62} {f.module:28} {flag}')
        by_method = Counter(f.method for f in found)
        self.stdout.write(f'\n{len(found)} operations; {sum(f.blocked for f in found)} blocked; '
                          f'{sum(not f.blocked for f in found)} reviewable; by method {dict(by_method)}')

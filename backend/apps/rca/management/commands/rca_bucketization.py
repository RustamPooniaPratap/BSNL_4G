"""Check stored RCA records against the approved taxonomy (apps.rca.taxonomy). Report only: nothing is changed.

    manage.py rca_bucketization                  # every Final Bucket / Sub Bucket combination, counts, status
    manage.py rca_bucketization --report out.csv # the same, as CSV

Values are never renamed, corrected or remapped (taxonomy rules of 4 Nov 2026): a record with an unapproved or
mismatched classification is corrected only through a corrected upload or by editing the record.
"""
import csv
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.rca import taxonomy
from apps.rca.models import RcaRecord


def plan() -> list[dict]:
    """Every distinct stored (Final Bucket, Sub Bucket) with its count, status and the approved names it matches."""
    rows = RcaRecord.all_objects.values('final_bucket', 'bucket_2').annotate(records=Count('id')).order_by('final_bucket', '-records')
    out = []
    for r in rows:
        res = taxonomy.resolve(r['final_bucket'], r['bucket_2'])
        out.append({'final_bucket': r['final_bucket'], 'bucket_2': r['bucket_2'], 'records': r['records'], 'status': res.status,
                    'approved_final_bucket': res.final_bucket or '', 'approved_bucket_2': res.bucket_2 or '',
                    'sub_bucket_belongs_to': ' / '.join(res.other_final_buckets)})
    return out


class Command(BaseCommand):
    help = 'Report stored RCA records by approved-taxonomy status (nothing is changed).'

    def add_arguments(self, parser):
        parser.add_argument('--report', help='Write every combination with its status to this CSV file.')

    def handle(self, *args, **options):
        items = plan()
        status = Counter()
        for i in items:
            status[i['status']] += i['records']
        total = sum(status.values())
        self.stdout.write(f'{len(items)} combinations, {total:,} records: ' + ', '.join(f'{k} {v:,}' for k, v in sorted(status.items())))
        if options['report']:
            path = Path(options['report'])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w', newline='', encoding='utf-8-sig') as handle:
                writer = csv.DictWriter(handle, fieldnames=['final_bucket', 'bucket_2', 'records', 'status', 'approved_final_bucket',
                                                            'approved_bucket_2', 'sub_bucket_belongs_to'])
                writer.writeheader()
                writer.writerows(items)
            self.stdout.write(f'Report: {path}')
        self.stdout.write('Report only: nothing was changed.')

"""Check stored RCA records against the approved bucketization (apps.rca.taxonomy) and correct only what is certain.

    manage.py rca_bucketization                  # dry run: every Final Bucket / Bucket - 2 combination, counts, status
    manage.py rca_bucketization --report out.csv # the same, as CSV
    manage.py rca_bucketization --apply          # write the corrections (one transaction)

A correction only gives a value its approved spelling where the two are equal ignoring case, spaces and punctuation, and a
Bucket - 2 only within its approved Final Bucket (taxonomy.resolve). Nothing else is changed: unresolved combinations
are reported, never reassigned or put in Others. Only final_bucket, bucket_2 and their matching keys are written, and each
corrected record gets an RcaEvent with the values before and after. Running it again changes nothing.
"""
import csv
from collections import Counter, defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from apps.rca import taxonomy
from apps.rca.models import RcaEvent, RcaRecord
from apps.rca.parser import text_key


def plan() -> list[dict]:
    """Every distinct stored (Final Bucket, Bucket - 2) with its count, status and approved spelling."""
    rows = RcaRecord.all_objects.values('final_bucket', 'bucket_2').annotate(records=Count('id')).order_by('final_bucket', '-records')
    out = []
    for r in rows:
        res = taxonomy.resolve(r['final_bucket'], r['bucket_2'])
        out.append({'final_bucket': r['final_bucket'], 'bucket_2': r['bucket_2'], 'records': r['records'], 'status': res.status,
                    'approved_final_bucket': res.final_bucket, 'approved_bucket_2': res.bucket_2,
                    'correction': (res.final_bucket, res.bucket_2) != (r['final_bucket'], r['bucket_2'])})
    return out


def apply(user=None) -> dict:
    """Write the certain corrections in one transaction; returns counts of corrected, already-correct and unresolved records."""
    counts = Counter()
    with transaction.atomic():
        by_pair = defaultdict(list)
        for rec in RcaRecord.all_objects.select_for_update().only('id', 'final_bucket', 'bucket_2', 'final_bucket_key', 'bucket_2_key'):
            by_pair[(rec.final_bucket, rec.bucket_2)].append(rec)
        for (final, b2), records in by_pair.items():
            res = taxonomy.resolve(final, b2)
            changed = (res.final_bucket, res.bucket_2) != (final, b2)
            if changed:
                for rec in records:
                    before = {'final_bucket': rec.final_bucket, 'bucket_2': rec.bucket_2}
                    rec.final_bucket, rec.bucket_2 = res.final_bucket, res.bucket_2
                    rec.final_bucket_key, rec.bucket_2_key = text_key(res.final_bucket), text_key(res.bucket_2)
                    rec.save(update_fields=['final_bucket', 'bucket_2', 'final_bucket_key', 'bucket_2_key', 'updated_at'])
                    RcaEvent.objects.create(record=rec, user=user, action='classification_corrected', changes={
                        f: {'from': before[f], 'to': getattr(rec, f)} for f in before if before[f] != getattr(rec, f)} | {
                        'rule': 'Approved bucketization: same name ignoring case, spaces and punctuation.'})
                counts['corrected'] += len(records)
            if res.status == 'approved':
                counts['approved_now' if changed else 'already_correct'] += len(records)
            else:
                counts['unresolved'] += len(records)
    return dict(counts)


class Command(BaseCommand):
    help = 'Check RCA records against the approved bucketization; --apply writes only the certain spelling corrections.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Write the corrections (otherwise a dry run).')
        parser.add_argument('--report', help='Write every combination with its status to this CSV file.')

    def handle(self, *args, **options):
        items = plan()
        status = Counter()
        for i in items:
            status[i['status']] += i['records']
        total = sum(status.values())
        self.stdout.write(f'{len(items)} combinations, {total:,} records: ' + ', '.join(f'{k} {v:,}' for k, v in sorted(status.items())))
        self.stdout.write(f'Corrections: {sum(i["records"] for i in items if i["correction"]):,} records in {sum(1 for i in items if i["correction"])} combinations.')
        if options['report']:
            path = Path(options['report'])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w', newline='', encoding='utf-8-sig') as handle:
                writer = csv.DictWriter(handle, fieldnames=['final_bucket', 'bucket_2', 'records', 'status', 'approved_final_bucket',
                                                            'approved_bucket_2', 'correction'])
                writer.writeheader()
                writer.writerows(items)
            self.stdout.write(f'Report: {path}')
        if options['apply']:
            result = apply()
            self.stdout.write(self.style.SUCCESS('Applied: ' + ', '.join(f'{k} {v:,}' for k, v in sorted(result.items()))))
        else:
            self.stdout.write('Dry run: nothing was changed (use --apply).')

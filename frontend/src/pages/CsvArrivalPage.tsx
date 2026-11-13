import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlarmClock, ArrowDown, ArrowUp, ArrowUpDown, BellRing, ChevronRight, CircleCheck, CircleDashed, ClipboardList, Database, FileUp, Info,
  Inbox, Mail, MessageSquarePlus, PhoneOff, RefreshCw, RotateCcw, Search, Settings2, UserPen,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { SelectField } from '../components/data/DataEntry';
import { Field as FilterField, FilterCard } from '../components/dashboard/FilterBar';
import { PageHeading } from '../context/pageHeader';
import { ArrivalForm, ComposeEmail, ContactForm, DeadlineForm, FollowUpForm, ReminderSend } from '../components/tracking/TrackingForms';
import { useTracking } from '../context/tracking';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { formatDate, formatDateTime, formatNumber } from '../lib/format';
import {
  DEFAULT_FILTERS, EMPTY_CONTACT, EMPTY_EMAIL, FOLLOW_UP_METHODS, deadlineParam, STATUS_LABELS, UPLOAD_LABELS, applyCard, applyFilters, buildSubmissions,
  kpis, localDate, newId, requirementKey, requirementsFrom, shortType, submissionKey,
  type ArrivalDraft, type ArrivalStatus, type CardFilter, type Submission, type TrackingFilters,
} from '../lib/tracking';
import { fetchArrivalTracker, fetchEmailStatus, fetchRawFiles } from '../services/api';
import type { EmailStatus, ReminderRequest } from '../types';
import type { ArrivalTracker, DataState, TrackerItem, UploadState } from '../types/rawUpload';

const STATUS_STYLE: Record<ArrivalStatus, string> = {
  complete: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  partial: 'border-amber-300 bg-amber-50 text-amber-800',
  file_received: 'border-sky-300 bg-sky-50 text-sky-800',
  no_data: 'border-slate-300 bg-slate-50 text-slate-700',
  late: 'border-red-300 bg-red-50 text-red-800',
};
const UPLOAD_STYLE: Record<UploadState, string> = {
  imported: 'border-emerald-300 text-emerald-800',
  awaiting_confirmation: 'border-sky-300 text-sky-800',
  nothing_to_import: 'border-slate-300 text-slate-700',
  blocked: 'border-red-300 text-red-800',
  failed: 'border-red-300 text-red-800',
  discarded: 'border-slate-300 text-slate-600',
  none: 'border-dashed border-slate-300 text-muted-foreground',
};
const CELL_STYLE: Record<DataState, string> = {
  complete: 'bg-emerald-500', partial: 'bg-amber-400', none: 'bg-slate-200', no_scope: 'bg-slate-100',
};
const STATUS_ORDER: Record<ArrivalStatus, number> = { late: 0, no_data: 1, file_received: 2, partial: 3, complete: 4 };
type SortKey = 'status' | 'circle' | 'reportType' | 'coverage' | 'latest' | 'followUp';
type Panel =
  | { kind: 'details'; key: string }
  | { kind: 'arrival'; draft: ArrivalDraft; editingKey?: string }
  | { kind: 'contact'; circle: string; reportType: string }
  | { kind: 'followup'; key: string }
  | { kind: 'deadlines' }
  | { kind: 'reminder'; key: string }
  | { kind: 'reminderPick' }
  | { kind: 'compose'; key?: string };
const PAGE_SIZE = 20;
const RANGE_DAYS = 14;
/** Reminders are for project/circles with neither stored data nor any upload for the date. */
const needsReminder = (s: Submission) => s.status === 'no_data' || s.status === 'late';
const reminderFor = (s: Submission): ReminderRequest => ({
  circle: s.circle, report_type: s.reportType, reporting_date: s.reportingDate, deadline: deadlineParam(s.deadline),
});
const shiftDate = (day: string, days: number) => {
  const d = new Date(`${day}T00:00:00`);
  d.setDate(d.getDate() + days);
  return localDate(d);
};

/** Current time, refreshed every minute so Late statuses appear when a deadline passes. Tests pass a fixed time. */
function useNow(fixed?: Date) {
  const [now, setNow] = useState(() => fixed ?? new Date());
  useEffect(() => {
    if (fixed) return;
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, [fixed]);
  return fixed ?? now;
}

/**
 * Daily 4G / LWE data by circle: stored daily-data coverage and raw CSV uploads come from the server for the selected
 * date; contacts, follow-ups, deadlines and manual arrival notes are held in this browser only.
 */
export function CsvArrivalPage({ now: fixedNow }: { now?: Date }) {
  const workbook = useWorkbook();
  const rawFiles = useApiQuery('raw-files', () => fetchRawFiles());
  const emailStatus = useApiQuery('email-status', fetchEmailStatus);
  const { state, dispatch } = useTracking();
  const now = useNow(fixedNow);
  const today = localDate(now);
  const [reportingDate, setReportingDate] = useState(today);
  const [range, setRange] = useState<{ start: string; end: string } | null>(null);  // null: the 14 days up to the reporting date
  const [reload, setReload] = useState(0);
  const [filters, setFilters] = useState<TrackingFilters>(DEFAULT_FILTERS);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'status', desc: false });
  const [page, setPage] = useState(1);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const setFilter = (changes: Partial<TrackingFilters>) => { setFilters((f) => ({ ...f, ...changes })); setPage(1); };

  const window_ = range ?? { start: shiftDate(reportingDate, -(RANGE_DAYS - 1)), end: reportingDate };
  // A new date, range, upload (workbook version) or Refresh fetches again; the previous request is aborted.
  const tracker = useApiQuery(`tracker|${reportingDate}|${window_.start}|${window_.end}|${workbook.version}|${reload}`,
    (signal) => fetchArrivalTracker({ date: reportingDate, ...window_ }, signal));
  // Never show another date's figures while the new ones load.
  const current: ArrivalTracker | null = tracker.data?.reporting_date === reportingDate ? tracker.data : null;

  const items = useMemo(() => current?.items ?? [], [current]);
  const requirements = useMemo(() => requirementsFrom(items), [items]);
  const submissions = useMemo(() => buildSubmissions(items, reportingDate, state, now), [items, reportingDate, state, now]);
  const filtered = useMemo(() => applyFilters(submissions, filters), [submissions, filters]);
  const counts = kpis(filtered);
  const rows = useMemo(() => {
    const value = (s: Submission): string | number => {
      switch (sort.key) {
        case 'circle': return s.circle;
        case 'reportType': return s.reportType;
        case 'coverage': return s.server.coverage_pct ?? -1;
        case 'latest': return s.server.latest_data_date ?? '';
        case 'followUp': return s.followUps[0]?.at ?? '';
        default: return STATUS_ORDER[s.status];
      }
    };
    return [...applyCard(filtered, filters.card)].sort((a, b) => {
      const [x, y] = [value(a), value(b)];
      const order = x < y ? -1 : x > y ? 1 : a.reportType.localeCompare(b.reportType) || a.circle.localeCompare(b.circle);
      return sort.desc ? -order : order;
    });
  }, [filtered, filters.card, sort]);

  const heading = (
    <PageHeading title="Data Arrival & Follow-up"
      subtitle={`${new Date(`${reportingDate}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short' })}, ${formatDate(reportingDate)}${reportingDate === today ? ' (today)' : ''} · stored daily 4G and LWE data, CSV uploads and follow-ups`} />
  );
  const dateField = (
    <FilterField id="track-date" label="Reporting date" className="w-40">
      <Input id="track-date" type="date" className="h-9" value={reportingDate} max={today}
        onChange={(e) => { if (e.target.value) { setReportingDate(e.target.value); setRange(null); setPage(1); } }} />
    </FilterField>
  );
  if (tracker.error && !current) {
    return (
      <div className="space-y-3">
        {heading}
        <FilterCard label="Tracking filters">{dateField}</FilterCard>
        <Alert variant="destructive" role="alert">
          <AlertTitle>The tracker could not be loaded</AlertTitle>
          <AlertDescription className="space-y-2">
            <p>{tracker.error.message}</p>
            <Button size="sm" variant="outline" onClick={() => setReload((n) => n + 1)}><RefreshCw /> Try again</Button>
          </AlertDescription>
        </Alert>
      </div>
    );
  }
  if (!current) {
    return (
      <div className="space-y-3">
        {heading}
        <FilterCard label="Tracking filters">{dateField}</FilterCard>
        <Skeleton className="h-96 w-full" aria-label="Loading CSV arrival tracking" />
      </div>
    );
  }

  const reportTypes = [...new Set(requirements.map((r) => r.reportType))];
  const circles = [...new Set(requirements.map((r) => r.circle))].sort();
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const shown = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const isDefault = JSON.stringify(filters) === JSON.stringify(DEFAULT_FILTERS);
  const pendingReports = submissions.filter(needsReminder);
  const pendingCount = pendingReports.length;
  const byKey = new Map(submissions.map((s) => [s.key, s]));
  const done = (text: string) => { setMessage(text); setPanel(null); };
  const recordArrival = (s?: Submission) => setPanel({
    kind: 'arrival',
    draft: { circle: s?.circle ?? '', reportType: s?.reportType ?? '', reportingDate, arrivalDate: '', arrivalTime: '', fileName: '', receivedBy: '', notes: '', timeIsEntryTime: false },
  });
  const editArrival = (s: Submission) => s.arrival && setPanel({
    kind: 'arrival', editingKey: s.key,
    draft: { circle: s.circle, reportType: s.reportType, reportingDate: s.reportingDate, arrivalDate: s.arrival.arrivalDate, arrivalTime: s.arrival.arrivalTime,
      fileName: s.arrival.fileName, receivedBy: s.arrival.receivedBy, notes: s.arrival.notes, timeIsEntryTime: s.arrival.timeIsEntryTime },
  });
  const toggleSort = (key: SortKey) => setSort((s) => ({ key, desc: s.key === key ? !s.desc : false }));
  const sortHead = (key: SortKey, label: string, className?: string) => (
    <TableHead className={className} aria-sort={sort.key === key ? (sort.desc ? 'descending' : 'ascending') : undefined}>
      <button type="button" onClick={() => toggleSort(key)} className="inline-flex items-center gap-1 rounded font-medium hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
        {label}
        {sort.key === key ? (sort.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />) : <ArrowUpDown className="size-3 opacity-40" />}
      </button>
    </TableHead>
  );

  const cards: { id: CardFilter; label: string; value: number; icon: ReactNode; tone?: string }[] = [
    { id: 'all', label: 'Project circles', value: counts.total, icon: <ClipboardList /> },
    { id: 'complete', label: 'Data complete', value: counts.complete, icon: <CircleCheck />, tone: 'text-emerald-700' },
    { id: 'partial', label: 'Partial data', value: counts.partial, icon: <CircleDashed />, tone: counts.partial ? 'text-amber-700' : undefined },
    { id: 'no_data', label: 'No usable data', value: counts.noData, icon: <Database /> },
    { id: 'csv_recorded', label: 'CSV uploads recorded', value: counts.csvRecorded, icon: <FileUp /> },
    { id: 'late', label: 'Past deadline', value: counts.late, icon: <AlarmClock />, tone: counts.late ? 'text-destructive' : undefined },
    { id: 'missing_contact', label: 'Missing contact details', value: counts.missingContact, icon: <PhoneOff />, tone: counts.missingContact ? 'text-amber-700' : undefined },
  ];

  return (
    <div className="space-y-3">
      {heading}
      <FilterCard label="Tracking filters"
        actions={(
          <>
            <EmailModeChip status={emailStatus.data} error={emailStatus.error} />
            <div role="group" aria-label="Email" className="inline-flex">
              <Button variant="outline" className="h-9 rounded-r-none" disabled={pendingCount === 0}
                title={pendingCount ? 'Send the standard reminder for a circle with no data and no upload' : 'Every circle has data or an upload for this date'}
                onClick={() => setPanel({ kind: 'reminderPick' })}>
                <BellRing /> Send reminder
              </Button>
              <Button variant="outline" className="-ml-px h-9 rounded-l-none" title="Write or edit an email before sending"
                onClick={() => setPanel({ kind: 'compose' })}>
                <Mail /> Compose email
              </Button>
            </div>
            <Button variant="outline" className="h-9" onClick={() => setPanel({ kind: 'deadlines' })}><Settings2 /> Deadlines</Button>
            <Button className="h-9" disabled={tracker.loading} onClick={() => setReload((n) => n + 1)}>
              <RefreshCw className={cn(tracker.loading && 'animate-spin')} /> Refresh
            </Button>
          </>
        )}>
        {dateField}
        <FilterField id="track-search" label="Search" className="w-56">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input id="track-search" type="search" value={filters.search} maxLength={80} className="h-9 pl-8"
              placeholder="Circle, contact, file, uploader" onChange={(e) => setFilter({ search: e.target.value })} />
          </div>
        </FilterField>
        <FilterField id="track-circle" label="Circle / State" className="w-36">
          <SelectField id="track-circle" value={filters.circle || 'all'} placeholder="All" onChange={(v) => setFilter({ circle: v === 'all' ? '' : v })}
            options={[{ value: 'all', label: 'All circles' }, ...circles.map((c) => ({ value: c, label: c }))]} />
        </FilterField>
        <FilterField id="track-type" label="Project" className="w-28">
          <SelectField id="track-type" value={filters.reportType || 'all'} placeholder="All" onChange={(v) => setFilter({ reportType: v === 'all' ? '' : v })}
            options={[{ value: 'all', label: 'All' }, ...reportTypes.map((t) => ({ value: t, label: shortType(t) }))]} />
        </FilterField>
        <FilterField id="track-status" label="Status" className="w-44">
          <SelectField id="track-status" value={filters.status || 'all'} placeholder="All" onChange={(v) => setFilter({ status: v === 'all' ? '' : (v as ArrivalStatus) })}
            options={[{ value: 'all', label: 'All statuses' }, ...(Object.keys(STATUS_LABELS) as ArrivalStatus[]).map((s) => ({ value: s, label: STATUS_LABELS[s] }))]} />
        </FilterField>
        <FilterField id="track-contact" label="Contact details" className="w-32">
          <SelectField id="track-contact" value={filters.contact} placeholder="All" onChange={(v) => setFilter({ contact: v as TrackingFilters['contact'] })}
            options={[{ value: 'all', label: 'All' }, { value: 'complete', label: 'Complete' }, { value: 'missing', label: 'Missing' }]} />
        </FilterField>
        <label className="flex h-9 items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" className="size-3.5 accent-primary" checked={filters.openOnly} onChange={(e) => setFilter({ openOnly: e.target.checked })} />
          Incomplete only
        </label>
        <Button variant="ghost" size="icon" className="size-9" aria-label="Clear filters" title="Clear filters" disabled={isDefault} onClick={() => setFilter(DEFAULT_FILTERS)}>
          <RotateCcw />
        </Button>
      </FilterCard>

      <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
        <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
        <p>
          Data status is read from the reporting data for the selected date: usable daily records ({current.usable_rule.toLowerCase()}) of the expected sites
          ({current.scope_rule}), whichever import wrote them. CSV upload status comes separately from the raw upload history.
          {' '}{current.notes[0]} Contacts, follow-ups, deadlines and manual arrival notes are held in this browser only.
        </p>
      </div>
      {message && (
        <Alert className="border-emerald-200 bg-emerald-50/70" role="status">
          <CircleCheck className="text-emerald-700" />
          <AlertTitle>{message}</AlertTitle>
          <AlertDescription>Held in this browser only; not saved to the server.</AlertDescription>
        </Alert>
      )}

      <section aria-label="Arrival summary" className="grid grid-cols-2 gap-2.5 md:grid-cols-4 xl:grid-cols-7">
        {cards.map((card) => {
          const active = filters.card === card.id && card.id !== 'all';
          return (
            <button key={card.id} type="button" aria-pressed={active}
              onClick={() => setFilter({ card: active ? 'all' : card.id })}
              className={cn('rounded-xl border bg-card px-3 py-2 text-left shadow-xs transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                active && 'border-primary ring-2 ring-primary/20')}>
              <span className="flex items-center justify-between text-[11px] font-medium text-muted-foreground [&_svg]:size-3.5">{card.label}{card.icon}</span>
              <span className={cn('mt-0.5 block text-[18px] leading-6 font-semibold tabular-nums', card.tone)}>{formatNumber(card.value)}</span>
              <span className="text-[10.5px] text-muted-foreground">{active ? 'Showing these · select to clear' : 'Select to filter the table'}</span>
            </button>
          );
        })}
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Circle-wise data and CSV uploads · {formatDate(reportingDate)}</CardTitle>
          <CardDescription className="text-xs">
            {formatNumber(rows.length)} of {formatNumber(submissions.length)} project circles shown. Select a row for its uploads, contact and follow-up history.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 px-0">
          {rows.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-sm text-muted-foreground">
              <Inbox className="size-6" aria-hidden="true" />
              <p>{submissions.length ? 'No circle matches these filters.' : 'No project circles in the site master for your circles.'}</p>
              {submissions.length > 0 && <Button variant="outline" size="sm" onClick={() => setFilter(DEFAULT_FILTERS)}>Clear filters</Button>}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    {sortHead('circle', 'Circle / State', 'pl-4')}
                    {sortHead('reportType', 'Project')}
                    {sortHead('status', 'Data status')}
                    {sortHead('coverage', 'Coverage')}
                    <TableHead>CSV upload</TableHead>
                    {sortHead('latest', 'Latest data')}
                    <TableHead>Expected by</TableHead>
                    <TableHead>Contact</TableHead>
                    {sortHead('followUp', 'Last follow-up')}
                    <TableHead className="pr-4 text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {shown.map((s) => {
                    const upload = s.server.uploads[0];
                    const source = sourceLabel(s.server);
                    return (
                      <TableRow key={s.key} className="cursor-pointer" tabIndex={0} aria-label={`${s.circle} ${shortType(s.reportType)}: open details`}
                        onClick={() => setPanel({ kind: 'details', key: s.key })}
                        onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setPanel({ kind: 'details', key: s.key }); } }}>
                        <TableCell className="pl-4 font-medium">{s.circle}</TableCell>
                        <TableCell><TypeBadge reportType={s.reportType} /></TableCell>
                        <TableCell>
                          <StatusBadge status={s.status} />
                          {source && <span className="mt-0.5 block text-[11px] text-muted-foreground">From {source}</span>}
                        </TableCell>
                        <TableCell className="whitespace-nowrap"><Coverage item={s.server} /></TableCell>
                        <TableCell className="max-w-56">
                          <UploadBadge state={s.server.upload_state} />
                          {upload && (
                            <span className="mt-0.5 block truncate text-[11px] text-muted-foreground" title={upload.file}>
                              {upload.file} · {formatDateTime(upload.uploaded_at)}{upload.uploaded_by ? ` · ${upload.uploaded_by}` : ''}
                              {s.server.uploads.length > 1 ? ` · +${s.server.uploads.length - 1} more` : ''}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {s.server.latest_data_date ? formatDate(s.server.latest_data_date) : <span className="text-muted-foreground">None stored</span>}
                          <span className="block text-[11px] text-muted-foreground">
                            Complete: {s.server.latest_complete_date ? formatDate(s.server.latest_complete_date) : '—'}
                          </span>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">{s.deadline ? formatDateTime(s.deadline.toISOString()) : <span className="text-muted-foreground">Not configured</span>}</TableCell>
                        <TableCell className="max-w-52">
                          {s.contact?.name ? (
                            <span className="block truncate" title={[s.contact.name, s.contact.phone, s.contact.email].filter(Boolean).join(' · ')}>
                              {s.contact.name}
                              <span className="block truncate text-[11px] text-muted-foreground">{[s.contact.phone, s.contact.email].filter(Boolean).join(' · ') || 'No phone or email'}</span>
                            </span>
                          ) : <span className="text-muted-foreground italic">Not added</span>}
                        </TableCell>
                        <TableCell className="max-w-44">
                          {s.followUps[0] ? (
                            <span className="block truncate" title={s.followUps[0].outcome}>
                              {formatDateTime(s.followUps[0].at)} · {FOLLOW_UP_METHODS[s.followUps[0].method]}
                              <span className="block truncate text-[11px] text-muted-foreground">{s.followUps[0].outcome}</span>
                            </span>
                          ) : <span className="text-muted-foreground">—</span>}
                        </TableCell>
                        <TableCell className="pr-4 text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                          {needsReminder(s) && (
                            <Button size="icon" variant="ghost" aria-label={`Send reminder for ${s.circle} ${shortType(s.reportType)}`} onClick={() => setPanel({ kind: 'reminder', key: s.key })}>
                              <BellRing />
                            </Button>
                          )}
                          <Button size="icon" variant="ghost" aria-label={`Add follow-up for ${s.circle} ${shortType(s.reportType)}`} onClick={() => setPanel({ kind: 'followup', key: s.key })}>
                            <MessageSquarePlus />
                          </Button>
                          <Button size="icon" variant="ghost" aria-label={`Edit contact for ${s.circle} ${shortType(s.reportType)}`} onClick={() => setPanel({ kind: 'contact', circle: s.circle, reportType: s.reportType })}>
                            <UserPen />
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
          {pages > 1 && (
            <nav className="flex items-center justify-between px-4 text-xs text-muted-foreground" aria-label="Table pagination">
              <span>Page {page} of {pages}</span>
              <div className="flex gap-1.5">
                <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
                <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
              </div>
            </nav>
          )}
        </CardContent>
      </Card>

      <CoverageRange key={`${current.range.start}|${current.range.end}`} tracker={current} rows={rows.map((s) => s.server)} today={today}
        onRange={(start, end) => setRange({ start, end })} onPick={(day) => { setReportingDate(day); setRange(range ?? window_); setPage(1); }} />

      <ServerFiles files={rawFiles.data?.files ?? []} loading={rawFiles.loading} error={rawFiles.error} />

      <Sheet open={panel !== null} onOpenChange={(open) => { if (!open) setPanel(null); }}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
          {panel?.kind === 'arrival' && (
            <>
              <SheetHeader>
                <SheetTitle>{panel.editingKey ? 'Edit manual arrival note' : 'Manual arrival note'}</SheetTitle>
                <SheetDescription>
                  For a file that arrived outside the portal (for example by email). Held in this browser only; it never changes the data or upload status.
                </SheetDescription>
              </SheetHeader>
              <div className="px-4 pb-6">
                <ArrivalForm initial={panel.draft} requirements={requirements} arrivals={state.arrivals} now={now}
                  editingId={panel.editingKey ? state.arrivals[panel.editingKey]?.id : undefined}
                  fileSuggestions={(rawFiles.data?.files ?? []).filter((f) => f.extension === '.csv').map((f) => f.name)}
                  onCancel={() => setPanel(null)}
                  onSave={(draft) => {
                    const key = submissionKey(draft, draft.reportingDate);
                    const previous = panel.editingKey ? state.arrivals[panel.editingKey] : undefined;
                    dispatch({
                      type: 'saveArrival', key, replaceKey: panel.editingKey,
                      record: { ...draft, id: previous?.id ?? newId('arrival'), enteredAt: previous?.enteredAt ?? new Date().toISOString() },
                    });
                    done(`${panel.editingKey ? 'Note updated' : 'Note recorded'} for ${draft.circle} · ${shortType(draft.reportType)} (${formatDate(draft.reportingDate)}).`);
                  }} />
              </div>
            </>
          )}
          {panel?.kind === 'contact' && (
            <>
              <SheetHeader>
                <SheetTitle>Contact · {panel.circle} {shortType(panel.reportType)}</SheetTitle>
                <SheetDescription>Who submits this circle's {shortType(panel.reportType)} CSV.</SheetDescription>
              </SheetHeader>
              <div className="px-4 pb-6">
                <ContactForm title={`${panel.circle} · ${panel.reportType}`}
                  initial={state.contacts[requirementKey(panel)] ?? EMPTY_CONTACT}
                  onCancel={() => setPanel(null)}
                  onSave={(contact) => {
                    dispatch({ type: 'saveContact', key: requirementKey(panel), contact });
                    done(`Contact saved for ${panel.circle} · ${shortType(panel.reportType)}.`);
                  }} />
              </div>
            </>
          )}
          {panel?.kind === 'followup' && byKey.get(panel.key) && (() => {
            const s = byKey.get(panel.key)!;
            return (
              <>
                <SheetHeader>
                  <SheetTitle>Add follow-up · {s.circle} {shortType(s.reportType)}</SheetTitle>
                  <SheetDescription>For the {formatDate(s.reportingDate)} CSV.</SheetDescription>
                </SheetHeader>
                <div className="px-4 pb-6">
                  <FollowUpForm title={`${s.circle} · ${s.reportType} (${formatDate(s.reportingDate)})`} contactName={s.contact?.name ?? ''} now={now}
                    onCancel={() => setPanel(null)}
                    onSave={(draft) => {
                      dispatch({ type: 'addFollowUp', followUp: { ...draft, id: newId('follow-up'), circle: s.circle, reportType: s.reportType, reportingDate: s.reportingDate, enteredAt: new Date().toISOString() } });
                      done(`Follow-up added for ${s.circle} · ${shortType(s.reportType)}.`);
                    }} />
                </div>
              </>
            );
          })()}
          {panel?.kind === 'reminderPick' && (
            <>
              <SheetHeader>
                <SheetTitle>Send reminder · {formatDate(reportingDate)}</SheetTitle>
                <SheetDescription>
                  Choose a circle with no stored data and no upload. You will see the recipient and the standard reminder before anything is sent.
                </SheetDescription>
              </SheetHeader>
              <div className="px-4 pb-6">
                {pendingReports.length === 0 ? <p className="text-sm text-muted-foreground">Every circle has data or an upload for this date.</p> : (
                  <ul className="divide-y rounded-lg border" aria-label="Circles without data">
                    {pendingReports.map((s) => (
                      <li key={s.key}>
                        <button type="button" onClick={() => setPanel({ kind: 'reminder', key: s.key })}
                          className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:outline-none">
                          <span className="w-10 font-medium">{s.circle}</span>
                          <TypeBadge reportType={s.reportType} />
                          <StatusBadge status={s.status} />
                          <span className={cn('ml-auto truncate text-xs', s.contact?.email.trim() ? 'text-muted-foreground' : 'text-destructive')}>
                            {s.contact?.email.trim() || 'No contact email'}
                          </span>
                          <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
          {panel?.kind === 'deadlines' && (
            <>
              <SheetHeader>
                <SheetTitle>Submission deadlines</SheetTitle>
                <SheetDescription>When each report type's CSV is due, relative to its reporting date.</SheetDescription>
              </SheetHeader>
              <div className="px-4 pb-6">
                <DeadlineForm reportTypes={reportTypes} config={state.deadlines} onCancel={() => setPanel(null)}
                  onSave={(config) => {
                    Object.entries(config).forEach(([reportType, deadline]) => dispatch({ type: 'setDeadline', reportType, deadline }));
                    done('Deadlines saved.');
                  }} />
              </div>
            </>
          )}
          {panel?.kind === 'reminder' && byKey.get(panel.key) && (() => {
            const s = byKey.get(panel.key)!;
            return (
              <>
                <SheetHeader>
                  <SheetTitle>Send reminder · {s.circle} {shortType(s.reportType)}</SheetTitle>
                  <SheetDescription>The standard reminder for the {formatDate(s.reportingDate)} CSV, sent to the circle's recorded contact.</SheetDescription>
                </SheetHeader>
                <div className="px-4 pb-6">
                  <ReminderSend reminder={reminderFor(s)} label={`${s.circle} · ${s.reportType} · ${formatDate(s.reportingDate)}`}
                    recipient={s.contact?.email.trim() ?? ''} status={emailStatus.data} statusError={emailStatus.error}
                    onAddContact={() => setPanel({ kind: 'contact', circle: s.circle, reportType: s.reportType })}
                    onCompose={() => setPanel({ kind: 'compose', key: s.key })} onCancel={() => setPanel(null)} />
                </div>
              </>
            );
          })()}
          {panel?.kind === 'compose' && (() => {
            const s = panel.key ? byKey.get(panel.key) : undefined;
            return (
              <>
                <SheetHeader>
                  <SheetTitle>Compose email{s ? ` · ${s.circle} ${shortType(s.reportType)}` : ''}</SheetTitle>
                  <SheetDescription>
                    {s ? `Start blank or load the standard reminder for the ${formatDate(s.reportingDate)} CSV, then edit it.` : 'Write a personal email.'}
                    {' '}Closing this panel never sends anything.
                  </SheetDescription>
                </SheetHeader>
                <div className="px-4 pb-6">
                  <ComposeEmail key={panel.key ?? 'blank'} initial={{ ...EMPTY_EMAIL, to: s?.contact?.email.trim() ?? '' }}
                    reminder={s ? reminderFor(s) : undefined} status={emailStatus.data} statusError={emailStatus.error} onCancel={() => setPanel(null)} />
                </div>
              </>
            );
          })()}
          {panel?.kind === 'details' && byKey.get(panel.key) && (
            <Details s={byKey.get(panel.key)!}
              onEditArrival={editArrival} onRecordArrival={recordArrival}
              onRemoveArrival={(s) => { dispatch({ type: 'removeArrival', key: s.key }); done(`Note removed for ${s.circle} · ${shortType(s.reportType)}.`); }}
              onContact={(s) => setPanel({ kind: 'contact', circle: s.circle, reportType: s.reportType })}
              onFollowUp={(s) => setPanel({ kind: 'followup', key: s.key })}
              onReminder={(s) => setPanel({ kind: 'reminder', key: s.key })} onCompose={(s) => setPanel({ kind: 'compose', key: s.key })} />
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

/** Small chip for the email backend in use: test mode never claims delivery. */
function EmailModeChip({ status, error }: { status: EmailStatus | null; error: Error | null }) {
  const chip = 'inline-flex h-7 shrink-0 items-center gap-1.5 self-start rounded-full border px-3 text-xs font-medium sm:self-auto';
  if (error) {
    return <span role="status" className={cn(chip, 'border-red-200 bg-red-50 text-red-800')} title={error.message}><span className="size-1.5 rounded-full bg-red-600" aria-hidden="true" />Email unavailable</span>;
  }
  if (!status) return <span role="status" className={cn(chip, 'text-muted-foreground')}>Checking email…</span>;
  return status.test_mode ? (
    <span role="status" className={cn(chip, 'border-amber-300 bg-amber-50 text-amber-800')}
      title={`Emails are printed in the backend terminal (${status.transport} backend); none are delivered.`}>
      <span className="size-1.5 rounded-full bg-amber-500" aria-hidden="true" />Email: test mode · not delivered
    </span>
  ) : (
    <span role="status" className={cn(chip, 'border-emerald-300 bg-emerald-50 text-emerald-800')} title={`Sent from ${status.from_email}`}>
      <span className="size-1.5 rounded-full bg-emerald-600" aria-hidden="true" />Email: live · {status.transport}
    </span>
  );
}

function StatusBadge({ status }: { status: ArrivalStatus }) {
  return <Badge variant="outline" className={cn('font-medium', STATUS_STYLE[status])}>{STATUS_LABELS[status]}</Badge>;
}

function UploadBadge({ state }: { state: UploadState }) {
  return <Badge variant="outline" className={cn('font-medium', UPLOAD_STYLE[state])}>{UPLOAD_LABELS[state]}</Badge>;
}

/** Which import wrote the usable records of the date (from each record's import batch). */
function sourceLabel(item: TrackerItem) {
  const { master_workbook: master, raw_daily_csv: raw, correction = 0 } = item.data_source;
  const parts = ([['Uptime Master', 'Uptime Master', master], ['raw CSV', 'Raw CSV upload', raw], ['correction', 'Admin correction', correction]] as const)
    .filter(([, , n]) => n > 0);
  if (!parts.length) return null;
  if (parts.length === 1) return parts[0][1];
  return parts.map(([label, , n]) => `${label} (${formatNumber(n)})`).join(' and ');
}

const pctText = (v: number) => `${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}%`;

/** "Inactive": the reporting unit is not expected to report on this date (deactivated, or not yet activated). */
function InactiveLabel() {
  return (
    <span className="mr-1 inline-flex items-center rounded-full border border-slate-300 bg-slate-100 px-1.5 text-[10px] font-medium text-slate-600"
      title="Reporting unit not expected on this date (inactive)">Inactive</span>
  );
}

function Coverage({ item }: { item: TrackerItem }) {
  const threshold = item.coverage_threshold_pct;
  if (item.active === false) {
    return <span className="text-muted-foreground"><InactiveLabel />Unit not expected on this date · {formatNumber(item.records_observed)} records</span>;
  }
  if (item.data_state === 'no_scope') {
    return <span className="text-muted-foreground">No On-Air sites in the master · {formatNumber(item.records_observed)} records</span>;
  }
  return (
    <span className="tabular-nums">
      {formatNumber(item.sites_with_data)} / {formatNumber(item.sites_expected)} sites
      <span className="block text-[11px] text-muted-foreground">
        {item.coverage_pct === null ? '—' : pctText(item.coverage_pct)}
        {threshold != null && <span title="Coverage threshold applied on this date"> (threshold {pctText(threshold)})</span>}
        {item.sites_missing ? ` · ${formatNumber(item.sites_missing)} missing` : ''}
        {item.sites_invalid ? ` · ${formatNumber(item.sites_invalid)} invalid` : ''}
      </span>
    </span>
  );
}

function TypeBadge({ reportType }: { reportType: string }) {
  return (
    <Badge variant="outline" className={cn('font-semibold', reportType === 'LWE' ? 'border-teal-300 text-teal-800' : 'border-blue-300 text-blue-800')}>
      {shortType(reportType)}
    </Badge>
  );
}

function ArrivalWhen({ record }: { record: Submission['arrival'] & object }) {
  return (
    <span>
      {record.arrivalDate ? formatDate(record.arrivalDate) : '—'} · {record.arrivalTime || '—'}
      {record.timeIsEntryTime && <span className="block text-[11px] text-muted-foreground">time of entry</span>}
    </span>
  );
}

/** Daily coverage per project circle across a date range, so gaps between dates are visible. Select a day to open it. */
function CoverageRange({ tracker, rows, today, onRange, onPick }: {
  tracker: ArrivalTracker; rows: TrackerItem[]; today: string; onRange: (start: string, end: string) => void; onPick: (day: string) => void;
}) {
  const [draft, setDraft] = useState(tracker.range);
  const days = rows[0]?.range.map((r) => r.date) ?? [];
  const tooLong = Boolean(draft.start && draft.end) && (new Date(`${draft.end}T00:00:00`).getTime() - new Date(`${draft.start}T00:00:00`).getTime()) / 86_400_000 >= 92;
  const invalid = !draft.start || !draft.end || draft.start > draft.end || tooLong;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-semibold">Daily coverage · {formatDate(tracker.range.start)} to {formatDate(tracker.range.end)}</CardTitle>
        <CardDescription className="text-xs">
          Usable records of the expected sites per day, from the reporting data. Grey days have no usable data. Select a day to open it above.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <form className="flex flex-wrap items-end gap-3" aria-label="Coverage range"
          onSubmit={(e) => { e.preventDefault(); if (!invalid) onRange(draft.start, draft.end); }}>
          <FilterField id="range-start" label="Range from" className="w-40">
            <Input id="range-start" type="date" className="h-9" value={draft.start} max={today} onChange={(e) => setDraft((d) => ({ ...d, start: e.target.value }))} />
          </FilterField>
          <FilterField id="range-end" label="Range to" className="w-40">
            <Input id="range-end" type="date" className="h-9" value={draft.end} max={today} onChange={(e) => setDraft((d) => ({ ...d, end: e.target.value }))} />
          </FilterField>
          <Button type="submit" variant="outline" className="h-9" disabled={invalid}>Show range</Button>
          {tooLong && <span className="text-xs text-destructive">Choose at most 92 days.</span>}
          {!tooLong && draft.start > draft.end && draft.end && <span className="text-xs text-destructive">The start is after the end.</span>}
          <span className="ml-auto flex items-center gap-3 text-[11px] text-muted-foreground" aria-hidden="true">
            {(['complete', 'partial', 'none'] as DataState[]).map((st) => (
              <span key={st} className="flex items-center gap-1"><span className={cn('size-2.5 rounded-sm', CELL_STYLE[st])} />{st === 'none' ? 'No data' : st === 'complete' ? 'Complete' : 'Partial'}</span>
            ))}
          </span>
        </form>
        {rows.length === 0 ? <p className="text-xs text-muted-foreground">No project circles to show.</p> : (
          <div className="overflow-x-auto">
            <table className="text-[11px]" aria-label="Daily coverage by circle">
              <thead>
                <tr>
                  <th className="pr-3 text-left font-medium text-muted-foreground">Circle</th>
                  {days.map((d) => (
                    <th key={d} className={cn('px-px font-normal text-muted-foreground', d === tracker.reporting_date && 'font-semibold text-foreground')} title={formatDate(d)}>{d.slice(8)}</th>
                  ))}
                  <th className="pl-3 text-left font-medium text-muted-foreground">Days without data</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((item) => {
                  const gaps = item.range.filter((r) => r.state === 'none').length;
                  return (
                    <tr key={`${item.project}|${item.circle}`}>
                      <td className="pr-3 whitespace-nowrap"><span className="font-medium">{item.circle}</span> {shortType(item.project)}</td>
                      {item.range.map((r) => (
                        <td key={r.date} className="px-px py-0.5">
                          <button type="button" onClick={() => onPick(r.date)}
                            aria-label={`${item.circle} ${shortType(item.project)} ${formatDate(r.date)}: ${r.state === 'none' ? 'no data' : `${formatNumber(r.sites_with_data)} of ${formatNumber(item.sites_expected)} sites`}`}
                            title={`${formatDate(r.date)}: ${r.state === 'no_scope' ? 'no On-Air sites or unit not expected (inactive)' : `${formatNumber(r.sites_with_data)} of ${formatNumber(item.sites_expected)} sites`}`}
                            className={cn('block size-4 rounded-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none', CELL_STYLE[r.state],
                              r.date === tracker.reporting_date && 'ring-2 ring-primary/60')} />
                        </td>
                      ))}
                      <td className={cn('pl-3 tabular-nums', gaps ? 'text-amber-700' : 'text-muted-foreground')}>{gaps}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Details({ s, onEditArrival, onRecordArrival, onRemoveArrival, onContact, onFollowUp, onReminder, onCompose }: {
  s: Submission; onEditArrival: (s: Submission) => void; onRecordArrival: (s: Submission) => void; onRemoveArrival: (s: Submission) => void;
  onContact: (s: Submission) => void; onFollowUp: (s: Submission) => void; onReminder: (s: Submission) => void; onCompose: (s: Submission) => void;
}) {
  const row = (label: string, value: ReactNode) => (
    <div className="grid grid-cols-[9rem_1fr] gap-2 py-1 text-sm"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="min-w-0 break-words">{value || '—'}</dd></div>
  );
  const item = s.server;
  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex flex-wrap items-center gap-2">{s.circle} <TypeBadge reportType={s.reportType} /> <StatusBadge status={s.status} /></SheetTitle>
        <SheetDescription>{formatDate(s.reportingDate)} · {s.deadline ? `due ${formatDateTime(s.deadline.toISOString())}` : 'no deadline configured'}</SheetDescription>
      </SheetHeader>
      <div className="space-y-4 px-4 pb-6">
        <section aria-label="Stored daily data">
          <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">Stored daily data (reporting data)</h3>
          <dl className="divide-y">
            {row('Expected sites', `${formatNumber(item.sites_expected)} On-Air of ${formatNumber(item.sites_total)} in the master`)}
            {row('With usable data', <Coverage item={item} />)}
            {item.coverage_threshold_pct != null && row('Coverage threshold', `${pctText(item.coverage_threshold_pct)} of expected sites (the threshold applied on this date)`)}
            {item.active === false && row('Reporting unit', <><InactiveLabel />Not expected on this date</>)}
            {row('Records written by', sourceLabel(item) ?? 'No usable records on this date')}
            {item.records_observed !== item.sites_with_data && row('All master sites', `${formatNumber(item.records_observed)} usable records, including sites not On-Air`)}
            {row('Latest data', item.latest_data_date ? formatDate(item.latest_data_date) : 'None stored')}
            {row('Latest complete date', item.latest_complete_date ? formatDate(item.latest_complete_date) : 'None')}
          </dl>
        </section>
        <section aria-label="CSV uploads">
          <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">Raw CSV uploads for {formatDate(s.reportingDate)}</h3>
          {item.uploads.length ? (
            <ol className="space-y-2">
              {item.uploads.map((u) => (
                <li key={u.id} className="rounded-md border px-3 py-2 text-sm">
                  <p className="flex flex-wrap items-center gap-2"><UploadBadge state={u.state} /><span className="truncate font-mono text-xs">{u.file}</span></p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Upload #{u.id} · {formatDateTime(u.uploaded_at)}{u.uploaded_by ? ` · ${u.uploaded_by}` : ''}
                    {u.imported !== null ? ` · ${formatNumber(u.imported)} records imported` : u.ready_to_import !== null ? ` · ${formatNumber(u.ready_to_import)} ready` : ''}
                    {u.rejected_count ? ` · ${formatNumber(u.rejected_count)} rows not imported` : ''}
                  </p>
                  {u.error && <p className="mt-1 text-xs text-destructive">{u.error}</p>}
                </li>
              ))}
            </ol>
          ) : <p className="text-sm text-muted-foreground">No CSV upload recorded for this date.</p>}
          <p className="mt-1 text-xs text-muted-foreground">
            Latest CSV received: {item.latest_upload_date ? formatDate(item.latest_upload_date) : '—'} · latest imported: {item.latest_import_date ? formatDate(item.latest_import_date) : '—'}
            {' · '}<Link className="underline underline-offset-2" to="/data/upload-csv">Uptime Data Upload</Link>
          </p>
        </section>
        <section aria-label="Contact">
          <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">Contact</h3>
          {s.contact && Object.values(s.contact).some(Boolean) ? (
            <dl className="divide-y">
              {row('Person', [s.contact.name, s.contact.designation].filter(Boolean).join(', '))}
              {row('Phone', s.contact.phone)}
              {row('Email', s.contact.email)}
              {row('Backup', s.contact.backup)}
              {row('Notes', s.contact.notes)}
            </dl>
          ) : <p className="text-sm text-muted-foreground">Not added.</p>}
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => onContact(s)}>{s.contact ? 'Edit contact' : 'Add contact'}</Button>
            {needsReminder(s) && <Button size="sm" variant="outline" onClick={() => onReminder(s)}><BellRing /> Send reminder now</Button>}
            <Button size="sm" variant="ghost" onClick={() => onCompose(s)}><Mail /> Compose email</Button>
          </div>
        </section>
        <section aria-label="Follow-up history">
          <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">Follow-ups for {formatDate(s.reportingDate)}</h3>
          {s.followUps.length ? (
            <ol className="space-y-2">
              {s.followUps.map((f) => (
                <li key={f.id} className="rounded-md border px-3 py-2 text-sm">
                  <p className="text-xs text-muted-foreground">{formatDateTime(f.at)} · {FOLLOW_UP_METHODS[f.method]}{f.contactPerson ? ` · ${f.contactPerson}` : ''}</p>
                  <p>{f.outcome}</p>
                  {(f.expectedAt || f.nextFollowUp) && (
                    <p className="text-xs text-muted-foreground">
                      {f.expectedAt && `Expected ${formatDateTime(f.expectedAt)}`}{f.expectedAt && f.nextFollowUp ? ' · ' : ''}{f.nextFollowUp && `Next follow-up ${formatDateTime(f.nextFollowUp)}`}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          ) : <p className="text-sm text-muted-foreground">No follow-ups recorded.</p>}
          <Button size="sm" variant="outline" className="mt-2" onClick={() => onFollowUp(s)}><MessageSquarePlus /> Add follow-up</Button>
        </section>
        <section aria-label="Manual arrival note">
          <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">Manual arrival note (this browser)</h3>
          {s.arrival ? (
            <>
              <dl className="divide-y">
                {row('Arrived', <ArrivalWhen record={s.arrival} />)}
                {row('File name', s.arrival.fileName)}
                {row('Received by', s.arrival.receivedBy)}
                {row('Notes', s.arrival.notes)}
                {row('Entered', `${formatDateTime(s.arrival.enteredAt)} (in this browser)`)}
              </dl>
              {s.problems.length > 0 && (
                <Alert className="mt-2 border-amber-300 bg-amber-50/70">
                  <AlertTitle>Check this note</AlertTitle>
                  <AlertDescription><ul className="list-disc pl-4">{s.problems.map((p) => <li key={p}>{p}</li>)}</ul></AlertDescription>
                </Alert>
              )}
              <div className="mt-2 flex gap-2">
                <Button size="sm" variant="outline" onClick={() => onEditArrival(s)}>Edit note</Button>
                <Button size="sm" variant="ghost" onClick={() => onRemoveArrival(s)}>Remove note</Button>
              </div>
            </>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">None. Use it for a file received outside the portal; it does not change the status.</p>
              <Button size="sm" variant="outline" onClick={() => onRecordArrival(s)}>Add manual note</Button>
            </div>
          )}
        </section>
      </div>
    </>
  );
}

function ServerFiles({ files, loading, error }: { files: { name: string; size_bytes: number; modified_at: string }[]; loading: boolean; error: Error | null }) {
  return (
    <details className="group rounded-xl border bg-card px-4 py-3 text-sm">
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground select-none">
        Files already on the server (Data/raw) · {loading ? '…' : files.length}
      </summary>
      <p className="mt-2 text-xs text-muted-foreground">
        For reference only: a file here does not mark any circle as received. The modified time is when the file was saved on the server, not when it arrived.
      </p>
      {error ? <p className="mt-2 text-xs text-destructive">{error.message}</p> : files.length ? (
        <ul className="mt-2 divide-y text-xs">
          {files.map((f) => (
            <li key={f.name} className="flex justify-between gap-3 py-1.5">
              <span className="truncate font-mono">{f.name}</span>
              <span className="shrink-0 text-muted-foreground">{formatDateTime(f.modified_at)}</span>
            </li>
          ))}
        </ul>
      ) : <p className="mt-2 text-xs text-muted-foreground">No files.</p>}
    </details>
  );
}

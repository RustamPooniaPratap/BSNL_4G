import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlarmClock, ArrowDown, ArrowUp, ArrowUpDown, BellRing, RotateCcw, ChevronRight, CircleCheck, ClipboardList, FileCheck2, Hourglass, Inbox, Info,
  Mail, MessageSquarePlus, PhoneOff, Plus, Search, Settings2, UserPen,
} from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { NoWorkbook, SelectField } from '../components/data/DataEntry';
import { Field as FilterField, FilterCard } from '../components/dashboard/FilterBar';
import { PageHeading } from '../context/pageHeader';
import { ArrivalForm, ComposeEmail, ContactForm, DeadlineForm, FollowUpForm, ReminderSend } from '../components/tracking/TrackingForms';
import { useTracking } from '../context/tracking';
import { useWorkbook } from '../context/workbook';
import { useApiQuery } from '../hooks/useApiQuery';
import { formatDate, formatDateTime, formatNumber } from '../lib/format';
import {
  DEFAULT_FILTERS, EMPTY_CONTACT, EMPTY_EMAIL, FOLLOW_UP_METHODS, deadlineParam, STATUS_LABELS, applyCard, applyFilters, buildSubmissions, kpis,
  localDate, newId, requirementKey, requirementsFrom, shortType, submissionKey,
  type ArrivalDraft, type ArrivalStatus, type CardFilter, type Submission, type TrackingFilters,
} from '../lib/tracking';
import { fetchEmailStatus, fetchFilterOptions, fetchRawFiles } from '../services/api';
import type { EmailStatus, ReminderRequest } from '../types';

const STATUS_STYLE: Record<ArrivalStatus, string> = {
  received: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  pending: 'border-slate-300 bg-slate-50 text-slate-700',
  late: 'border-red-300 bg-red-50 text-red-800',
  needs_review: 'border-amber-300 bg-amber-50 text-amber-800',
};
const STATUS_ORDER: Record<ArrivalStatus, number> = { late: 0, pending: 1, needs_review: 2, received: 3 };
type SortKey = 'status' | 'circle' | 'reportType' | 'arrival' | 'followUp';
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
/** Only pending or late submissions get a reminder. */
const needsReminder = (s: Submission) => s.status === 'pending' || s.status === 'late';
const reminderFor = (s: Submission): ReminderRequest => ({
  circle: s.circle, report_type: s.reportType, reporting_date: s.reportingDate, deadline: deadlineParam(s.deadline),
});

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

/** Daily 4G / LWE raw CSV arrivals by circle, with contacts and follow-ups (held in the browser only). */
export function CsvArrivalPage({ now: fixedNow }: { now?: Date }) {
  const workbook = useWorkbook();
  const options = useApiQuery(workbook.active ? `${workbook.version}|filters` : null, fetchFilterOptions);
  const rawFiles = useApiQuery('raw-files', () => fetchRawFiles());
  const emailStatus = useApiQuery('email-status', fetchEmailStatus);
  const { state, dispatch } = useTracking();
  const now = useNow(fixedNow);
  const today = localDate(now);
  const [reportingDate, setReportingDate] = useState(today);
  const [filters, setFilters] = useState<TrackingFilters>(DEFAULT_FILTERS);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'status', desc: false });
  const [page, setPage] = useState(1);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const setFilter = (changes: Partial<TrackingFilters>) => { setFilters((f) => ({ ...f, ...changes })); setPage(1); };

  const requirements = useMemo(() => requirementsFrom(options.data?.circles ?? []), [options.data]);
  const submissions = useMemo(() => buildSubmissions(requirements, reportingDate, state, now), [requirements, reportingDate, state, now]);
  const filtered = useMemo(() => applyFilters(submissions, filters), [submissions, filters]);
  const counts = kpis(filtered, today);
  const rows = useMemo(() => {
    const value = (s: Submission): string | number => {
      switch (sort.key) {
        case 'circle': return s.circle;
        case 'reportType': return s.reportType;
        case 'arrival': return s.arrival ? `${s.arrival.arrivalDate}T${s.arrival.arrivalTime}` : '';
        case 'followUp': return s.followUps[0]?.at ?? '';
        default: return STATUS_ORDER[s.status];
      }
    };
    return [...applyCard(filtered, filters.card, today)].sort((a, b) => {
      const [x, y] = [value(a), value(b)];
      const order = x < y ? -1 : x > y ? 1 : a.reportType.localeCompare(b.reportType) || a.circle.localeCompare(b.circle);
      return sort.desc ? -order : order;
    });
  }, [filtered, filters.card, today, sort]);

  if (!workbook.loading && !workbook.active) return <NoWorkbook />;
  if (!options.data) return <Skeleton className="h-96 w-full" aria-label="Loading CSV arrival tracking" />;

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
    { id: 'all', label: 'Reporting circles', value: counts.total, icon: <ClipboardList /> },
    { id: 'received', label: 'CSVs received', value: counts.received, icon: <CircleCheck />, tone: 'text-emerald-700' },
    { id: 'pending', label: 'CSVs pending', value: counts.pending, icon: <Hourglass /> },
    { id: 'received_today', label: 'Received today', value: counts.receivedToday, icon: <FileCheck2 /> },
    { id: 'late', label: 'Late submissions', value: counts.late, icon: <AlarmClock />, tone: counts.late ? 'text-destructive' : undefined },
    { id: 'missing_contact', label: 'Missing contact details', value: counts.missingContact, icon: <PhoneOff />, tone: counts.missingContact ? 'text-amber-700' : undefined },
  ];

  return (
    <div className="space-y-4">
      <PageHeading title="CSV Arrival & Follow-up"
        subtitle={`${new Date(`${reportingDate}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short' })}, ${formatDate(reportingDate)}${reportingDate === today ? ' (today)' : ''} · daily 4G and LWE submissions, pending reports and follow-ups`} />
      <FilterCard label="Tracking filters"
        actions={(
          <>
            <EmailModeChip status={emailStatus.data} error={emailStatus.error} />
            <div role="group" aria-label="Email" className="inline-flex">
              <Button variant="outline" className="h-9 rounded-r-none" disabled={pendingCount === 0}
                title={pendingCount ? 'Send the standard reminder for a pending report' : 'No pending reports for this date'}
                onClick={() => setPanel({ kind: 'reminderPick' })}>
                <BellRing /> Send reminder
              </Button>
              <Button variant="outline" className="-ml-px h-9 rounded-l-none" title="Write or edit an email before sending"
                onClick={() => setPanel({ kind: 'compose' })}>
                <Mail /> Compose email
              </Button>
            </div>
            <Button variant="outline" className="h-9" onClick={() => setPanel({ kind: 'deadlines' })}><Settings2 /> Deadlines</Button>
            <Button className="h-9" onClick={() => recordArrival()}><Plus /> Record arrival</Button>
          </>
        )}>
        <FilterField id="track-date" label="Reporting date" className="w-40">
          <Input id="track-date" type="date" className="h-9" value={reportingDate}
            onChange={(e) => { if (e.target.value) { setReportingDate(e.target.value); setPage(1); } }} />
        </FilterField>
        <FilterField id="track-search" label="Search" className="w-56">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input id="track-search" type="search" value={filters.search} maxLength={80} className="h-9 pl-8"
              placeholder="Circle, contact, file, phone, email" onChange={(e) => setFilter({ search: e.target.value })} />
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
        <FilterField id="track-status" label="Arrival status" className="w-36">
          <SelectField id="track-status" value={filters.status || 'all'} placeholder="All" onChange={(v) => setFilter({ status: v === 'all' ? '' : (v as ArrivalStatus) })}
            options={[{ value: 'all', label: 'All statuses' }, ...(Object.keys(STATUS_LABELS) as ArrivalStatus[]).map((s) => ({ value: s, label: STATUS_LABELS[s] }))]} />
        </FilterField>
        <FilterField id="track-contact" label="Contact details" className="w-32">
          <SelectField id="track-contact" value={filters.contact} placeholder="All" onChange={(v) => setFilter({ contact: v as TrackingFilters['contact'] })}
            options={[{ value: 'all', label: 'All' }, { value: 'complete', label: 'Complete' }, { value: 'missing', label: 'Missing' }]} />
        </FilterField>
        <label className="flex h-9 items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" className="size-3.5 accent-primary" checked={filters.openOnly} onChange={(e) => setFilter({ openOnly: e.target.checked })} />
          Late / pending only
        </label>
        <Button variant="ghost" size="icon" className="size-9" aria-label="Clear filters" title="Clear filters" disabled={isDefault} onClick={() => setFilter(DEFAULT_FILTERS)}>
          <RotateCcw />
        </Button>
      </FilterCard>

      <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
        <Info className="mt-px size-3.5 shrink-0" aria-hidden="true" />
        Changes are currently held in the frontend; persistent storage is not enabled. They are kept while you move between pages and lost on refresh.
        Circles come from the Master workbook ({formatNumber(requirements.length)} circle and report type pairs); arrivals, contacts and follow-ups appear only once recorded here.
      </p>
      {message && (
        <Alert className="border-emerald-200 bg-emerald-50/70" role="status">
          <CircleCheck className="text-emerald-700" />
          <AlertTitle>{message}</AlertTitle>
          <AlertDescription>Held in this browser only; not saved to the server.</AlertDescription>
        </Alert>
      )}

      <section aria-label="Arrival summary" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {cards.map((card) => {
          const active = filters.card === card.id && card.id !== 'all';
          return (
            <button key={card.id} type="button" aria-pressed={active}
              onClick={() => setFilter({ card: active ? 'all' : card.id })}
              className={cn('rounded-xl border bg-card px-4 py-3 text-left shadow-xs transition-colors hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                active && 'border-primary ring-2 ring-primary/20')}>
              <span className="flex items-center justify-between text-xs font-medium text-muted-foreground [&_svg]:size-3.5">{card.label}{card.icon}</span>
              <span className={cn('mt-1 block text-2xl font-semibold tabular-nums', card.tone)}>{formatNumber(card.value)}</span>
              <span className="text-[11px] text-muted-foreground">{active ? 'Showing these · select to clear' : 'Select to filter the table'}</span>
            </button>
          );
        })}
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-semibold">Circle-wise submissions · {formatDate(reportingDate)}</CardTitle>
          <CardDescription className="text-xs">
            {formatNumber(rows.length)} of {formatNumber(submissions.length)} requirements shown. Select a row for its details, contact and follow-up history.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 px-0">
          {rows.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-sm text-muted-foreground">
              <Inbox className="size-6" aria-hidden="true" />
              <p>No circle matches these filters.</p>
              <Button variant="outline" size="sm" onClick={() => setFilter(DEFAULT_FILTERS)}>Clear filters</Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    {sortHead('circle', 'Circle / State', 'pl-4')}
                    {sortHead('reportType', 'Report')}
                    {sortHead('status', 'Arrival status')}
                    <TableHead>Expected by</TableHead>
                    {sortHead('arrival', 'Arrived')}
                    <TableHead>File name</TableHead>
                    <TableHead>Contact</TableHead>
                    {sortHead('followUp', 'Last follow-up')}
                    <TableHead className="pr-4 text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {shown.map((s) => (
                    <TableRow key={s.key} className="cursor-pointer" tabIndex={0} aria-label={`${s.circle} ${shortType(s.reportType)}: open details`}
                      onClick={() => setPanel({ kind: 'details', key: s.key })}
                      onKeyDown={(e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setPanel({ kind: 'details', key: s.key }); } }}>
                      <TableCell className="pl-4 font-medium">{s.circle}</TableCell>
                      <TableCell><TypeBadge reportType={s.reportType} /></TableCell>
                      <TableCell>
                        <StatusBadge status={s.status} />
                        {s.arrivedLate && <span className="ml-1 text-[11px] text-amber-700">after deadline</span>}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{s.deadline ? formatDateTime(s.deadline.toISOString()) : <span className="text-muted-foreground">Not configured</span>}</TableCell>
                      <TableCell className="whitespace-nowrap">
                        {s.arrival ? <ArrivalWhen record={s.arrival} /> : <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell className="max-w-44 truncate" title={s.arrival?.fileName}>{s.arrival?.fileName || <span className="text-muted-foreground">—</span>}</TableCell>
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
                        {s.arrival
                          ? <Button size="sm" variant="ghost" onClick={() => editArrival(s)}>Edit arrival</Button>
                          : <Button size="sm" variant="outline" onClick={() => recordArrival(s)}>Record arrival</Button>}
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
                  ))}
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

      <ServerFiles files={rawFiles.data?.files ?? []} loading={rawFiles.loading} error={rawFiles.error} />

      <Sheet open={panel !== null} onOpenChange={(open) => { if (!open) setPanel(null); }}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
          {panel?.kind === 'arrival' && (
            <>
              <SheetHeader>
                <SheetTitle>{panel.editingKey ? 'Edit arrival' : 'Record CSV arrival'}</SheetTitle>
                <SheetDescription>Enter when the CSV actually arrived. One arrival per circle, report type and reporting date.</SheetDescription>
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
                    done(`${panel.editingKey ? 'Arrival updated' : 'Arrival recorded'} for ${draft.circle} · ${shortType(draft.reportType)} (${formatDate(draft.reportingDate)}).`);
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
                  Choose a pending report. You will see the recipient and the standard reminder before anything is sent.
                </SheetDescription>
              </SheetHeader>
              <div className="px-4 pb-6">
                {pendingReports.length === 0 ? <p className="text-sm text-muted-foreground">No pending reports for this date.</p> : (
                  <ul className="divide-y rounded-lg border" aria-label="Pending reports">
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
              onRemoveArrival={(s) => { dispatch({ type: 'removeArrival', key: s.key }); done(`Arrival removed for ${s.circle} · ${shortType(s.reportType)}.`); }}
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

function Details({ s, onEditArrival, onRecordArrival, onRemoveArrival, onContact, onFollowUp, onReminder, onCompose }: {
  s: Submission; onEditArrival: (s: Submission) => void; onRecordArrival: (s: Submission) => void; onRemoveArrival: (s: Submission) => void;
  onContact: (s: Submission) => void; onFollowUp: (s: Submission) => void; onReminder: (s: Submission) => void; onCompose: (s: Submission) => void;
}) {
  const row = (label: string, value: ReactNode) => (
    <div className="grid grid-cols-[9rem_1fr] gap-2 py-1 text-sm"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="min-w-0 break-words">{value || '—'}</dd></div>
  );
  return (
    <>
      <SheetHeader>
        <SheetTitle className="flex items-center gap-2">{s.circle} <TypeBadge reportType={s.reportType} /> <StatusBadge status={s.status} /></SheetTitle>
        <SheetDescription>CSV for {formatDate(s.reportingDate)} · {s.deadline ? `due ${formatDateTime(s.deadline.toISOString())}` : 'no deadline configured'}</SheetDescription>
      </SheetHeader>
      <div className="space-y-5 px-4 pb-6">
        <section aria-label="Arrival">
          <h3 className="mb-1 text-xs font-semibold text-muted-foreground uppercase">Arrival</h3>
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
                  <AlertTitle>Needs review</AlertTitle>
                  <AlertDescription><ul className="list-disc pl-4">{s.problems.map((p) => <li key={p}>{p}</li>)}</ul></AlertDescription>
                </Alert>
              )}
              <div className="mt-2 flex gap-2">
                <Button size="sm" variant="outline" onClick={() => onEditArrival(s)}>Edit arrival</Button>
                <Button size="sm" variant="ghost" onClick={() => onRemoveArrival(s)}>Remove arrival</Button>
              </div>
            </>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">No arrival recorded for this date.</p>
              <Button size="sm" onClick={() => onRecordArrival(s)}>Record arrival</Button>
            </div>
          )}
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

import { useCallback, useEffect, useMemo, useState } from 'react';
import { PageHeading } from '../../context/pageHeader';
import {
  downloadAllCircleEmails, downloadReportFile, fetchReportOptions, fetchReportOverview, fetchReportPreview, fetchReportRuns, saveSchedule, sendReport,
} from './api';
import { ConfirmButton, DataStatusNote, DistributionMaster, Messages, StatusPill } from './shared';
import { errorText, fmt, saveBlob, useAction } from './utils';
import type { ReportOptions, ReportOverview, ReportPreview, ReportRun, ReportType } from './types';
import './bsnl.css';

const TABS: { id: ReportType; label: string }[] = [{ id: 'D-1', label: 'Daily D-1 report' }, { id: 'Weekly', label: 'Weekly report' }];
const dateText = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });

/**
 * Auto Email Reports (reference "Auto email reports"): the D-1 report daily and the weekly report every Monday, per
 * Circle, to the Distribution Master list. Figures come from the portal's approved uptime / NSLA rules (On-Air sites).
 */
export function AutoEmailReportsPage() {
  const [type, setType] = useState<ReportType>('D-1');
  const [circle, setCircle] = useState('');
  const [project, setProject] = useState('');
  const [options, setOptions] = useState<ReportOptions | null>(null);
  const [loadedOverview, setOverview] = useState<{ key: string; data: ReportOverview } | null>(null);
  const [loadedPreview, setPreview] = useState<{ key: string; data: ReportPreview | null; error: string } | null>(null);
  const [runs, setRuns] = useState<ReportRun[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const action = useAction();

  useEffect(() => {
    const controller = new AbortController();
    fetchReportOptions(controller.signal).then(setOptions).catch((cause) => {
      if (!controller.signal.aborted) setLoadError(errorText(cause, 'Auto Email Reports could not be loaded.'));
    });
    return () => controller.abort();
  }, [refresh]);

  useEffect(() => {
    const controller = new AbortController();
    const key = `${type}|${project}|${refresh}`;
    fetchReportOverview(type, project, controller.signal).then((data) => { setOverview({ key, data }); setLoadError(''); }).catch((cause) => {
      if (!controller.signal.aborted) setLoadError(errorText(cause, 'The circle reports could not be loaded.'));
    });
    return () => controller.abort();
  }, [type, project, refresh]);

  const overview = loadedOverview?.key === `${type}|${project}|${refresh}` ? loadedOverview.data : null;
  const canPreview = circle !== '' || !!options?.permissions.all_india;
  const previewKey = `${type}|${circle}|${project}`;
  useEffect(() => {
    if (!options || !canPreview) return;
    const controller = new AbortController();
    fetchReportPreview(type, circle, project, controller.signal).then((data) => setPreview({ key: previewKey, data, error: '' })).catch((cause) => {
      if (!controller.signal.aborted) setPreview({ key: previewKey, data: null, error: errorText(cause, 'The email preview could not be built.') });
    });
    return () => controller.abort();
  }, [type, circle, project, options, canPreview, previewKey]);
  const previewState = canPreview && loadedPreview?.key === previewKey ? loadedPreview : null;
  const preview = previewState?.data ?? null;
  const previewError = previewState?.error ?? '';

  const loadRuns = useCallback((signal?: AbortSignal) => {
    fetchReportRuns(signal).then((data) => setRuns(data.runs)).catch(() => { if (!signal?.aborted) setRuns([]); });
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    loadRuns(controller.signal);
    return () => controller.abort();
  }, [loadRuns]);

  const circles = useMemo(() => (overview?.circles ?? []).map((c) => ({ code: c.circle, name: c.name })), [overview]);
  const scopeName = circle ? circles.find((c) => c.code === circle)?.name ?? circle : 'All India';
  const sites = circle ? overview?.circles.find((c) => c.circle === circle)?.sites : overview?.circles.reduce((t, c) => t + c.sites, 0);

  const download = (key: string, fetcher: () => Promise<{ blob: Blob; filename: string }>, done: string) =>
    action.run(key, async () => { const { blob, filename } = await fetcher(); saveBlob(blob, filename); return done; });
  const send = (target: string) => action.run(`send-${target}`, async () => {
    const { run } = await sendReport(type, target, project);
    loadRuns();
    return `Email accepted by the mail server for ${run.circle_name} (${run.to.join(', ')}).`;
  });
  const setSchedule = (next: { daily: boolean; weekly: boolean }) => action.run('schedule', async () => {
    await saveSchedule(next);
    setRefresh((v) => v + 1);
    return 'Schedule saved.';
  });

  const schedule = options?.schedule;
  const scheduleOn = type === 'D-1' ? schedule?.daily : schedule?.weekly;
  return (
    <div className="bsm">
      <PageHeading title="Auto Email Reports" subtitle="BSNL Module · D-1 and weekly Circle reports" />
      <div className="card pad">
        <div className="title">
          <div>
            <div className="crumb">{circle ? <><button type="button" className="link" onClick={() => setCircle('')}>All India</button> › <b>{scopeName}</b></> : <b>All India</b>}</div>
            <h2>Auto email reports – {scopeName}</h2>
            <div className="note">
              D-1 report daily and weekly report every Monday, per Circle, to the Distribution Master list.
              {overview && <> · Period {overview.period.label} · As of {dateText(overview.latest_date)} · {fmt(sites ?? 0)} sites</>}
              {project && <> · {project}</>} · SLA target {fmt(options?.target_pct ?? 98.5, 2)}% · {options?.population ?? 'On-Air sites'}
            </div>
          </div>
          <div className="filters">
            <div className="f"><label htmlFor="ar-circle">Circle</label>
              <select id="ar-circle" value={circle} onChange={(e) => setCircle(e.target.value)}>
                <option value="">All India</option>{circles.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
              </select></div>
            <div className="f"><label htmlFor="ar-category">Site category</label>
              <select id="ar-category" value={project} onChange={(e) => setProject(e.target.value)}>
                <option value="">All</option>{(options?.projects ?? []).map((p) => <option key={p}>{p}</option>)}
              </select></div>
          </div>
        </div>
      </div>
      {loadError && <div role="alert" className="errbox">{loadError}</div>}

      <div className="card pad">
        <div className="tabs" role="tablist">
          {TABS.map((t) => <button key={t.id} type="button" role="tab" aria-selected={type === t.id} className={type === t.id ? 'on' : ''} onClick={() => setType(t.id)}>{t.label}</button>)}
        </div>
        <div className="stat" style={{ marginTop: 12 }}>
          <div><div className="l">Report period</div><div className="v">{overview?.period.label ?? '…'}</div></div>
          <div><div className="l">Schedule (server)</div><div className="v">{type === 'D-1' ? 'Daily 09:00 IST' : 'Monday 10:00 IST'}</div>
            <div className="note">{scheduleOn ? 'Automatic sending on' : 'Automatic sending off'}{options && !options.sending_enabled ? ' · sending disabled on this server' : ''}</div></div>
          <div><div className="l">Recipients loaded</div><div className="v num">{options ? `${fmt(options.recipients_loaded)} rows` : '…'}</div></div>
          <div><div className="l">Attachment</div><div className="v">Excel</div></div>
        </div>
        <p className="note" style={{ margin: '10px 0 0' }}>
          This page builds each Circle&apos;s email and attachment from the portal&apos;s uptime and RCA data. &quot;Download email&quot; saves a
          ready-to-send .eml draft (opens in Outlook with To, Cc, subject, body and Excel attached) and never sends anything.
          Unattended sending at the scheduled time runs on the server worker with the same content, once it is switched on.
        </p>
        {options?.permissions.manage && schedule && (
          <div className="btns" style={{ marginTop: 10 }}>
            <ConfirmButton label={schedule.daily ? 'Switch off daily D-1 sending' : 'Switch on daily D-1 sending'} busy={action.busy !== null}
              message={schedule.daily ? 'Stop the automatic D-1 emails?' : 'Send the D-1 report automatically every day at 09:00 IST to the Distribution Master?'}
              onConfirm={() => setSchedule({ ...schedule, daily: !schedule.daily })} />
            <ConfirmButton label={schedule.weekly ? 'Switch off weekly sending' : 'Switch on weekly sending'} busy={action.busy !== null}
              message={schedule.weekly ? 'Stop the automatic weekly emails?' : 'Send the weekly report automatically every Monday at 10:00 IST to the Distribution Master?'}
              onConfirm={() => setSchedule({ ...schedule, weekly: !schedule.weekly })} />
          </div>
        )}
      </div>
      <Messages error={action.error} notice={action.notice} />
      <DataStatusNote status={overview?.data_status} />

      {!circle && (
        <div className="card pad">
          <div className="title">
            <h4 style={{ margin: 0 }}>Circle distribution – {type} report</h4>
            <div className="btns">
              <button type="button" className="btn primary" disabled={action.busy !== null || !overview}
                onClick={() => download('all', () => downloadAllCircleEmails(type, project), 'All Circle emails downloaded (one .eml per Circle, in a ZIP).')}>
                {action.busy === 'all' ? 'Preparing…' : 'Download all Circle emails'}</button>
              {options?.permissions.all_india && (
                <button type="button" className="btn" disabled={action.busy !== null}
                  onClick={() => download('india', () => downloadReportFile(type, '', project, 'eml'), 'All India summary email downloaded.')}>Download All India summary email</button>
              )}
            </div>
          </div>
          <div className="tbox" style={{ marginTop: 10 }}>
            <table aria-label="Circle distribution">
              <thead><tr><th>Circle</th><th className="r">Uptime %</th><th>Status</th><th className="r">Not meeting SLA</th>
                <th className="r" title="Sites with an outage on at least one reported day (the portal's USD rule)">USD sites</th>
                <th className="r">Outage Minutes</th><th>To / Cc</th><th /></tr></thead>
              <tbody>
                {!overview && !loadError && <tr><td colSpan={8} className="note">Loading circle reports…</td></tr>}
                {overview?.circles.length === 0 && <tr><td colSpan={8} className="note">No circles in your access.</td></tr>}
                {overview?.circles.map((c) => (
                  <tr key={c.circle}>
                    <td><b>{c.name}</b>{!c.complete && <div className="note">Your access covers part of this circle</div>}</td>
                    <td className="r num">{fmt(c.uptime_pct, 3)}</td><td><StatusPill status={c.status} /></td>
                    <td className="r num">{fmt(c.not_meeting_sla)}</td><td className="r num">{fmt(c.usd_sites)}</td>
                    <td className="r num">{fmt(c.outage_minutes)}</td>
                    <td className="note wrap">{c.to.length ? c.to.join(', ') : <span className="up-bad">No recipients</span>}{c.cc.length > 0 && <><br />Cc: {c.cc.join(', ')}</>}</td>
                    <td><div className="btns">
                      <button type="button" className="btn" onClick={() => { setCircle(c.circle); window.scrollTo?.({ top: 0 }); }}>Preview</button>
                      <button type="button" className="btn primary" disabled={action.busy !== null} aria-label={`Download email ${c.name}`}
                        onClick={() => download(`eml-${c.circle}`, () => downloadReportFile(type, c.circle, project, 'eml'), `${c.name} email downloaded.`)}>Download email</button>
                    </div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card pad">
        <div className="title">
          <h4 style={{ margin: 0 }}>Email preview – {circle ? scopeName : 'All India summary'}</h4>
          {preview && (
            <div className="btns">
              <button type="button" className="btn primary" disabled={action.busy !== null}
                onClick={() => download('eml', () => downloadReportFile(type, circle, project, 'eml'), 'Email downloaded (.eml). Nothing was sent.')}>Download email (.eml)</button>
              <button type="button" className="btn" disabled={action.busy !== null}
                onClick={() => download('xls', () => downloadReportFile(type, circle, project, 'xlsx'), 'Excel attachment downloaded.')}>Download Excel attachment</button>
              {options?.permissions.send && (circle ? overview?.circles.find((c) => c.circle === circle)?.can_send : options.permissions.all_india) && (
                <ConfirmButton label="Send now" busy={action.busy !== null} disabled={!options.sending_enabled || preview.to.length === 0}
                  message={`Send this email now to ${preview.to.join(', ')}${preview.cc.length ? ` (Cc ${preview.cc.join(', ')})` : ''}?`}
                  confirmLabel="Send email" onConfirm={() => send(circle)} />
              )}
            </div>
          )}
        </div>
        {options?.permissions.send && !options.sending_enabled && <p className="note">Sending is disabled on this server; use the downloads.</p>}
        {!canPreview && <p className="note" style={{ marginTop: 10 }}>Choose a Circle to preview its email (the All India summary needs access to every circle).</p>}
        {previewError && <div role="alert" className="errbox" style={{ marginTop: 10 }}>{previewError}</div>}
        {canPreview && !preview && !previewError && <p className="note" style={{ marginTop: 10 }}>Building the email preview…</p>}
        {preview && (
          <div className="mail" style={{ marginTop: 10 }}>
            <div className="mh" aria-label="Email header">
              <b>To</b><span>{preview.to.length ? preview.to.join(', ') : <span className="up-bad">No recipients in Distribution Master</span>}</span>
              <b>Cc</b><span>{preview.cc.join(', ') || '–'}</span>
              <b>Subject</b><span>{preview.subject}</span>
              <b>Period</b><span>{preview.period.label}</span>
              <b>Attach</b><span>{preview.attachment} ({preview.sheet_count} sheets)</span>
            </div>
            <div className="mb"><iframe title="Email body" sandbox="" srcDoc={`<html><body style="margin:16px">${preview.html}</body></html>`} /></div>
          </div>
        )}
      </div>

      <DistributionMaster title="Distribution Master – report recipients" reportTypes={['D-1', 'Weekly', 'All India']} circles={circles}
        onChange={() => setRefresh((v) => v + 1)} />

      <div className="card pad">
        <h4>Delivery history</h4>
        <div className="tbox"><table aria-label="Delivery history"><thead><tr><th>When</th><th>Report</th><th>Circle</th><th>Period</th><th>Trigger</th><th>Status</th><th>To</th><th>Detail</th></tr></thead>
          <tbody>{runs === null ? <tr><td colSpan={8} className="note">Loading…</td></tr> : runs.length ? runs.map((r) => (
            <tr key={r.id}><td>{new Date(r.created_at).toLocaleString('en-IN')}</td><td>{r.report_type}</td><td>{r.circle_name}</td>
              <td>{r.period_start === r.period_end ? r.period_start : `${r.period_start} – ${r.period_end}`}</td><td>{r.trigger === 'schedule' ? 'Scheduled' : `Manual (${r.created_by})`}</td>
              <td><span className={`status ${r.status === 'sent' ? 's-good' : r.status === 'failed' ? 's-crit' : 's-warn'}`}><i />{r.status === 'sent' ? 'Accepted by SMTP' : r.status}</span></td>
              <td className="wrap note">{r.to.join(', ')}</td><td className="wrap note">{r.error || r.smtp_response}</td></tr>
          )) : <tr><td colSpan={8} className="note">No report email has been sent yet.</td></tr>}</tbody></table></div>
      </div>
    </div>
  );
}

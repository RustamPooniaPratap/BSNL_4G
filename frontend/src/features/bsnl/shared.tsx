import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { errorText, useAction } from './utils';
import { createRecipient, fetchRecipients, updateRecipient, type RecipientInput } from './api';
import type { DataStatus, Recipient, RecipientReportType } from './types';

const PILL: Record<string, string> = {
  'Meets SLA': 's-good', 'Minor breach': 's-warn', Breach: 's-crit',
  Approved: 's-warn', Sent: 's-good', Acknowledged: 's-good', 'Exclusion accepted': 's-good', 'Exclusion rejected': 's-crit',
};
export function StatusPill({ status }: { status: string }) {
  return <span className={`status ${PILL[status] ?? ''}`}><i />{status}</span>;
}

export function Messages({ error, notice }: { error?: string; notice?: string }) {
  return (
    <>
      {error && <div role="alert" className="errbox">{error}</div>}
      {notice && <div role="status" className="okbox">{notice}</div>}
    </>
  );
}

/** A button that asks for confirmation in place before running (approval, sending, schedule changes). */
export function ConfirmButton({ label, confirmLabel, message, onConfirm, disabled, primary, busy }: {
  label: string; confirmLabel?: string; message: ReactNode; onConfirm: () => void; disabled?: boolean; primary?: boolean; busy?: boolean;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return <button type="button" className={`btn${primary ? ' primary' : ''}`} disabled={disabled || busy} onClick={() => setAsking(true)}>{label}</button>;
  }
  return (
    <div className="confirm" role="group" aria-label={`Confirm: ${label}`}>
      <span>{message}</span>
      <button type="button" className="btn primary sm" disabled={busy} onClick={() => { setAsking(false); onConfirm(); }}>{confirmLabel ?? 'Confirm'}</button>
      <button type="button" className="btn sm" disabled={busy} onClick={() => setAsking(false)}>Cancel</button>
    </div>
  );
}

export function DataStatusNote({ status }: { status: DataStatus | undefined }) {
  if (!status || status.status !== 'Provisional') return null;
  const units = [...new Set(status.missing.flatMap((m) => m.units))].sort();
  return <div className="warnbox">Data status: Provisional – data not yet received for {units.join(', ')}. Figures may change when it arrives.</div>;
}

const EMPTY_ROW = (reportType: RecipientReportType): RecipientInput => ({
  circle: '', report_type: reportType, name: '', designation: '', email: '', kind: 'To', is_active: true,
});

/**
 * The Distribution Master (reference "Distribution Master" sheet): To / Cc per Circle and report type, persisted on the
 * server. Rows are deactivated, never deleted. Editing needs the module's Manage permission (checked by the server).
 */
export function DistributionMaster({ reportTypes, circles, title, onChange }: {
  reportTypes: RecipientReportType[]; circles: { code: string; name: string }[]; title: string; onChange?: () => void;
}) {
  const [rows, setRows] = useState<Recipient[] | null>(null);
  const [canManage, setCanManage] = useState<Partial<Record<RecipientReportType, boolean>>>({});
  const [draft, setDraft] = useState<RecipientInput>(EMPTY_ROW(reportTypes[0]));
  const [loadError, setLoadError] = useState('');
  const { busy, error, notice, run } = useAction();
  const types = reportTypes.join('|');

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await fetchRecipients(undefined, signal);
      setRows(data.recipients.filter((r) => types.split('|').includes(r.report_type)));
      setCanManage(data.can_manage);
      setLoadError('');
    } catch (cause) {
      if (!signal?.aborted) setLoadError(errorText(cause, 'Recipients could not be loaded.'));
    }
  }, [types]);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const manageable = reportTypes.filter((t) => canManage[t]);
  const save = () => run('add', async () => {
    await createRecipient({ ...draft, circle: draft.report_type === 'All India' ? '' : draft.circle });
    setDraft(EMPTY_ROW(draft.report_type));
    await load();
    onChange?.();
    return 'Recipient added.';
  });
  const toggle = (r: Recipient) => run(`toggle-${r.id}`, async () => {
    await updateRecipient(r.id, { circle: r.circle, report_type: r.report_type, name: r.name, designation: r.designation, email: r.email, kind: r.kind, is_active: !r.is_active });
    await load();
    onChange?.();
    return r.is_active ? 'Recipient deactivated.' : 'Recipient activated.';
  });

  return (
    <div className="card pad">
      <div className="title"><h4>{title}</h4><span className="note">{rows ? `${rows.filter((r) => r.is_active).length} active rows` : ''}</span></div>
      {loadError && <div role="alert" className="errbox">{loadError}</div>}
      <Messages error={error} notice={notice} />
      {manageable.length > 0 && (
        <form className="filters" style={{ margin: '8px 0 12px' }} onSubmit={(e) => { e.preventDefault(); save(); }} aria-label={`Add recipient to ${title}`}>
          <div className="f"><label htmlFor="rcp-type">Report</label>
            <select id="rcp-type" value={draft.report_type} onChange={(e) => setDraft({ ...draft, report_type: e.target.value as RecipientReportType })}>
              {manageable.map((t) => <option key={t}>{t}</option>)}
            </select></div>
          {draft.report_type !== 'All India' && (
            <div className="f"><label htmlFor="rcp-circle">Circle</label>
              <select id="rcp-circle" value={draft.circle} required onChange={(e) => setDraft({ ...draft, circle: e.target.value })}>
                <option value="">Choose…</option>{circles.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
              </select></div>
          )}
          <div className="f"><label htmlFor="rcp-name">Name</label><input id="rcp-name" type="text" required maxLength={120} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></div>
          <div className="f"><label htmlFor="rcp-desig">Designation</label><input id="rcp-desig" type="text" maxLength={120} value={draft.designation} onChange={(e) => setDraft({ ...draft, designation: e.target.value })} /></div>
          <div className="f"><label htmlFor="rcp-email">Email</label><input id="rcp-email" type="email" required maxLength={254} value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} /></div>
          <div className="f"><label htmlFor="rcp-kind">To / Cc</label>
            <select id="rcp-kind" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as 'To' | 'Cc' })}><option>To</option><option>Cc</option></select></div>
          <button type="submit" className="btn primary" disabled={busy !== null}>{busy === 'add' ? 'Adding…' : 'Add recipient'}</button>
        </form>
      )}
      {rows === null && !loadError ? <p className="note">Loading recipients…</p> : (
        <div className="tbox"><table aria-label={title}><thead><tr><th>Circle</th><th>Report</th><th>Name</th><th>Designation</th><th>Email</th><th>To/Cc</th><th>Status</th><th /></tr></thead>
          <tbody>{(rows ?? []).length ? (rows ?? []).map((r) => (
            <tr key={r.id} className={r.is_active ? '' : 'muted'}>
              <td>{r.circle_name}</td><td>{r.report_type}</td><td>{r.name}</td><td>{r.designation}</td><td>{r.email}</td><td>{r.kind}</td>
              <td>{r.is_active ? 'Active' : 'Inactive'}</td>
              <td>{canManage[r.report_type] && <button type="button" className="btn sm" disabled={busy !== null} onClick={() => toggle(r)}>{r.is_active ? 'Deactivate' : 'Activate'}</button>}</td>
            </tr>
          )) : <tr><td colSpan={8} className="note">No recipients yet.</td></tr>}</tbody></table></div>
      )}
    </div>
  );
}

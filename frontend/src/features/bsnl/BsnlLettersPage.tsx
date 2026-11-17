import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { PageHeading } from '../../context/pageHeader';
import {
  approveLetter, downloadLetterFile, downloadLetterRegister, fetchBucketMapping, fetchLetter, fetchLetterOptions, fetchLetterOverview,
  fetchProfiles, openLetter, regenerateLetter, saveBucketMapping, saveLetterContent, saveProfile, sendLetter, setLetterStatus,
  type LetterPeriodQuery,
} from './api';
import { ConfirmButton, DistributionMaster, Messages, StatusPill } from './shared';
import { errorText, fmt, saveBlob, useAction } from './utils';
import type { BucketMapping, CircleProfile, LetterDetail, LetterOptions, LetterOverview, LetterPeriodKind, LetterStatus } from './types';
import './bsnl.css';

const PERIODS: { id: LetterPeriodKind; label: string }[] = [{ id: 'd1', label: 'D-1' }, { id: 'week', label: 'Last week' }, { id: 'period', label: 'Selected From–To' }];
const day = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
const STATUS_ACTIONS: Partial<Record<LetterStatus, string>> = {
  Draft: 'Return to Draft', Sent: 'Mark as sent outside the portal', Acknowledged: 'Mark acknowledged by BSNL',
  'Exclusion accepted': 'Exclusion accepted', 'Exclusion rejected': 'Exclusion rejected',
};

/**
 * BSNL Letters (reference "BSNL letters"): a letter per Circle listing the Customer (BSNL)-bucket outages of the RCA
 * records, for review, approval and email to BSNL. Letters, edits and status changes are stored on the server.
 */
export function BsnlLettersPage() {
  const [options, setOptions] = useState<LetterOptions | null>(null);
  const [kind, setKind] = useState<LetterPeriodKind>('period');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [circle, setCircle] = useState('');
  const [project, setProject] = useState('');
  const [loadedOverview, setOverview] = useState<{ key: string; data: LetterOverview } | null>(null);
  const [letter, setLetter] = useState<LetterDetail | null>(null);
  const loadedId = useRef<number | null>(null);
  useEffect(() => { loadedId.current = letter?.id ?? null; }, [letter]);
  const [loadError, setLoadError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const action = useAction();

  useEffect(() => {
    const controller = new AbortController();
    fetchLetterOptions(controller.signal).then((data) => {
      setOptions(data);
      if (data.latest_rca_date) {
        setTo(data.latest_rca_date);
        setFrom(`${data.latest_rca_date.slice(0, 8)}01`);
      }
    }).catch((cause) => { if (!controller.signal.aborted) setLoadError(errorText(cause, 'BSNL Letters could not be loaded.')); });
    return () => controller.abort();
  }, []);

  const query: LetterPeriodQuery = useMemo(() => ({ period: kind, date_from: kind === 'period' ? from : '', date_to: kind === 'period' ? to : '', project }), [kind, from, to, project]);
  const ready = !!options && (kind !== 'period' || (!!from && !!to));
  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    const key = `${JSON.stringify(query)}|${refresh}`;
    fetchLetterOverview(query, controller.signal).then((data) => { setOverview({ key, data }); setLoadError(''); }).catch((cause) => {
      if (!controller.signal.aborted) setLoadError(errorText(cause, 'The letter overview could not be loaded.'));
    });
    return () => controller.abort();
  }, [query, ready, refresh]);

  const overview = loadedOverview?.key === `${JSON.stringify(query)}|${refresh}` ? loadedOverview.data : null;
  const row = overview?.circles.find((c) => c.circle === circle);
  const letterId = row?.letter?.id;
  useEffect(() => {
    // Only a letter that is not already loaded here: a fetch started by the overview refresh after a local change must
    // never replace the newer letter that change returned.
    if (!letterId || loadedId.current === letterId) return;
    const controller = new AbortController();
    fetchLetter(letterId, controller.signal).then((data) => setLetter((current) => (current?.id === data.letter.id ? current : data.letter))).catch((cause) => {
      if (!controller.signal.aborted) action.setError(errorText(cause, 'The letter could not be loaded.'));
    });
    return () => controller.abort();
  }, [letterId]); // eslint-disable-line react-hooks/exhaustive-deps

  // The open letter stays on screen while the overview reloads (after a save or status change); it is hidden only when
  // the circle, category or period no longer match it.
  const showLetter = !!letter && !!circle && letter.circle === circle && letter.project === project
    && (overview ? letter.period_start === overview.period.start && letter.period_end === overview.period.end && letter.id === letterId : true);
  const circles = useMemo(() => (overview?.circles ?? []).map((c) => ({ code: c.circle, name: c.name })), [overview]);
  const scopeName = circle ? row?.name ?? circle : 'All India';
  const updated = (next: LetterDetail, message: string) => { setLetter(next); setRefresh((v) => v + 1); return message; };
  const prepare = () => action.run('open', async () => {
    const result = await openLetter(circle, query);
    return updated(result.letter, result.created ? `Draft letter ${result.letter.reference} prepared.` : `Letter ${result.letter.reference} opened.`);
  });
  const openFromRegister = (l: LetterOverview['register'][number]) => {
    setProject(l.project);
    setKind('period');
    setFrom(l.period_start);
    setTo(l.period_end);
    setCircle(l.circle);
  };

  return (
    <div className="bsm">
      <PageHeading title="BSNL Letters" subtitle="BSNL Module · Customer (BSNL)-bucket outage letters" />
      <div className="card pad">
        <div className="title">
          <div>
            <div className="crumb">{circle ? <><button type="button" className="link" onClick={() => setCircle('')}>All India</button> › <b>{scopeName}</b></> : <b>All India</b>}</div>
            <h2>BSNL letters – {scopeName}</h2>
            <div className="note">Auto-drafted letter per Circle listing Customer (BSNL)-bucket outages, for review, approval and email to BSNL.
              {options?.latest_rca_date && <> · RCA data to {day(options.latest_rca_date)}</>}{project && <> · {project}</>}</div>
          </div>
          <div className="filters">
            <div className="f"><label htmlFor="bl-circle">Circle</label>
              <select id="bl-circle" value={circle} onChange={(e) => setCircle(e.target.value)}>
                <option value="">All India</option>{circles.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
              </select></div>
            <div className="f"><label htmlFor="bl-category">Site category</label>
              <select id="bl-category" value={project} onChange={(e) => setProject(e.target.value)}>
                <option value="">All</option>{(options?.projects ?? []).map((p) => <option key={p}>{p}</option>)}
              </select></div>
          </div>
        </div>
      </div>

      <div className="card pad">
        <div className="title">
          <div className="btns">
            {PERIODS.map((p) => <button key={p.id} type="button" className={`btn${kind === p.id ? ' primary' : ''}`} aria-pressed={kind === p.id} onClick={() => setKind(p.id)}>{p.label}</button>)}
            {kind === 'period' && (
              <>
                <div className="f"><label htmlFor="bl-from">From</label><input id="bl-from" type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} /></div>
                <div className="f"><label htmlFor="bl-to">To</label><input id="bl-to" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></div>
              </>
            )}
          </div>
          <span className="note">Letter period: {overview ? overview.period.label : '…'}</span>
        </div>
      </div>
      {loadError && <div role="alert" className="errbox">{loadError}</div>}
      <Messages error={action.error} notice={action.notice} />

      {!circle && (
        <div className="card pad">
          <h4>Customer (BSNL)-bucket outages by Circle</h4>
          <div className="tbox"><table aria-label="Customer outages by circle">
            <thead><tr><th>Circle</th><th className="r">Outages</th><th className="r">Sites</th><th className="r">Outage Minutes</th><th>BSNL recipients</th><th>Letter</th><th /></tr></thead>
            <tbody>
              {!overview && !loadError && <tr><td colSpan={7} className="note">Loading…</td></tr>}
              {overview?.circles.length === 0 && <tr><td colSpan={7} className="note">No circles in your access.</td></tr>}
              {overview?.circles.map((c) => (
                <tr key={c.circle}>
                  <td><b>{c.name}</b></td><td className="r num">{fmt(c.outages)}</td><td className="r num">{fmt(c.sites)}</td><td className="r num">{fmt(c.outage_minutes)}</td>
                  <td className="note wrap">{c.to.length ? c.to.join(', ') : <span className="up-bad">No BSNL contact</span>}</td>
                  <td>{c.letter ? <>{c.letter.reference} <StatusPill status={c.letter.status} /></> : <span className="note">–</span>}</td>
                  <td><button type="button" className="btn primary" aria-label={`Open letter ${c.name}`} onClick={() => setCircle(c.circle)}>Open letter</button></td>
                </tr>
              ))}
            </tbody></table></div>
          <p className="note" style={{ margin: '8px 0 0' }}>Choose a Circle in the dropdown or click &quot;Open letter&quot; to draft it.</p>
        </div>
      )}

      {circle && overview && !row && <div className="card pad"><p>{scopeName} is not in your access for this site category.</p></div>}
      {circle && row && !row.letter && (
        <div className="card pad">
          {row.outages === 0 ? <p>No Customer (BSNL)-bucket outages in {row.name} for this period, so no letter is needed.</p> : (
            <>
              <p><b>{fmt(row.outages)}</b> Customer (BSNL)-bucket outages at <b>{fmt(row.sites)}</b> sites, <b>{fmt(row.outage_minutes)} Outage Minutes</b>, in {row.name} for {overview?.period.label}.</p>
              {options?.permissions.edit && row.complete
                ? <button type="button" className="btn primary" disabled={action.busy !== null} onClick={prepare}>{action.busy === 'open' ? 'Preparing…' : 'Prepare draft letter'}</button>
                : <p className="note">No letter has been prepared for this period yet{row.complete ? '' : ' (preparing it needs access to every project of the circle, or choose one site category)'}.</p>}
            </>
          )}
        </div>
      )}
      {showLetter && letter && <LetterView key={`${letter.id}-${letter.updated_at}`} letter={letter} action={action} onChange={updated} />}

      <div className="card pad">
        <div className="title"><h4 style={{ margin: 0 }}>Letter register ({overview?.register.length ?? 0})</h4>
          <button type="button" className="btn" disabled={action.busy !== null} onClick={() => action.run('register', async () => {
            const { blob, filename } = await downloadLetterRegister(); saveBlob(blob, filename); return 'Register exported.';
          })}>Export register</button></div>
        {overview?.register.length ? (
          <div className="tbox" style={{ marginTop: 8 }}><table aria-label="Letter register">
            <thead><tr><th>Ref</th><th>Circle</th><th>Period</th><th className="r">Outages</th><th className="r">Outage Minutes</th><th>Prepared</th><th>Status</th></tr></thead>
            <tbody>{overview.register.map((l) => (
              <tr key={l.id}><td><button type="button" className="link" onClick={() => openFromRegister(l)}>{l.reference}</button></td><td>{l.circle_name}{l.project && ` (${l.project})`}</td>
                <td>{l.period_label}</td><td className="r num">{fmt(l.outage_count)}</td><td className="r num">{fmt(l.total_minutes)}</td>
                <td>{new Date(l.created_at).toLocaleString('en-IN')} · {l.prepared_by}</td><td><StatusPill status={l.status} /></td></tr>
            ))}</tbody></table></div>
        ) : <p className="note">No letters prepared yet.</p>}
        <p className="note" style={{ margin: '6px 0 0' }}>The register is stored on the server with each letter&apos;s status history.</p>
      </div>

      <details className="card pad">
        <summary>Letter masters – BSNL recipients, circle contacts and sender, RCA bucket mapping</summary>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 12 }}>
          <DistributionMaster title="BSNL letter recipients" reportTypes={['BSNL letter']} circles={circles} onChange={() => setRefresh((v) => v + 1)} />
          <ProfilesEditor />
          <BucketMappingEditor />
        </div>
      </details>
    </div>
  );
}

function LetterView({ letter, action, onChange }: {
  letter: LetterDetail; action: ReturnType<typeof useAction>; onChange: (letter: LetterDetail, message: string) => string;
}) {
  const body = useRef<HTMLDivElement>(null);
  const [dirty, setDirty] = useState(false);
  const [note, setNote] = useState('');
  const editable = letter.status === 'Draft' && letter.permissions.edit;
  const rc = letter.recipients ?? {};
  const busy = action.busy !== null;
  const file = (kind: 'doc' | 'xlsx' | 'eml', done: string) => action.run(kind, async () => {
    const { blob, filename } = await downloadLetterFile(letter.id, kind); saveBlob(blob, filename); return done;
  });
  const print = () => action.run('print', async () => {
    const { blob } = await downloadLetterFile(letter.id, 'html');
    const w = window.open('', '_blank');
    if (!w) throw new Error('The print window was blocked by the browser. Allow pop-ups for the portal and try again.');
    w.document.write(await blob.text());
    w.document.close();
    w.focus();
    w.print();
  });

  return (
    <div className="card pad">
      <div className="title">
        <div>
          <h4 style={{ margin: 0 }}>{letter.status === 'Draft' ? 'Draft letter' : 'Letter'} – {letter.circle_name}{letter.project && ` (${letter.project})`} · {letter.reference} <StatusPill status={letter.status} /></h4>
          <div className="note">
            {editable ? 'Click in the letter to edit any text, then save the edits. ' : ''}
            To: {rc.to?.length ? rc.to.join(', ') : <span className="up-bad">no BSNL contact in Distribution Master</span>}{rc.cc?.length ? ` · Cc: ${rc.cc.join(', ')}` : ''}
            {letter.edited ? ' · Edited (the generated version is kept)' : ' · As generated'}
            {letter.approved_by && ` · Approved by ${letter.approved_by} on ${new Date(letter.approved_at!).toLocaleString('en-IN')}`}
          </div>
        </div>
        <div className="btns">
          {editable && <button type="button" className="btn primary" disabled={busy || !dirty} onClick={() => action.run('save', async () => {
            const result = await saveLetterContent(letter.id, body.current?.innerHTML ?? '');
            return onChange(result.letter, 'Letter edits saved.');
          })}>{action.busy === 'save' ? 'Saving…' : 'Save edits'}</button>}
          {editable && <ConfirmButton label="Regenerate from data" busy={busy} message="Rebuild the letter from the current RCA records? Unsaved and saved edits are replaced."
            onConfirm={() => action.run('regen', async () => onChange((await regenerateLetter(letter.id)).letter, 'Letter regenerated from the RCA records.'))} />}
          {letter.status === 'Draft' && letter.permissions.approve && (
            <ConfirmButton label="Approve letter" primary busy={busy} disabled={dirty}
              message={`Approve ${letter.reference} for ${rc.to?.join(', ') || 'no recipient'}? It can no longer be edited.`}
              onConfirm={() => action.run('approve', async () => onChange((await approveLetter(letter.id)).letter, `Letter ${letter.reference} approved.`))} />
          )}
          {letter.status !== 'Draft' && <button type="button" className="btn" disabled={busy} onClick={() => file('eml', 'Email downloaded (.eml). Nothing was sent and the status is unchanged.')}>Download email (.eml)</button>}
          <button type="button" className="btn" disabled={busy || dirty} onClick={() => file('doc', 'Letter downloaded (Word).')}>Download letter (Word)</button>
          <button type="button" className="btn" disabled={busy} onClick={() => file('xlsx', 'Annexure downloaded (Excel).')}>Download annexure (Excel)</button>
          <button type="button" className="btn" disabled={busy || dirty} onClick={print}>Print / PDF</button>
          {letter.status === 'Approved' && letter.permissions.send && (
            <ConfirmButton label="Send email to BSNL" primary busy={busy} disabled={!letter.sending_enabled || !rc.to?.length}
              message={`Send ${letter.reference} now to ${rc.to?.join(', ')}${rc.cc?.length ? ` (Cc ${rc.cc.join(', ')})` : ''} with the Word letter and Excel annexure?`}
              confirmLabel="Send email" onConfirm={() => action.run('send', async () => {
                const next = (await sendLetter(letter.id)).letter;
                return onChange(next, next.send_status === 'sent' ? `Letter ${letter.reference} accepted by the mail server.` : `Sending failed: ${next.send_error}`);
              })} />
          )}
        </div>
      </div>
      {letter.status === 'Approved' && letter.permissions.send && !letter.sending_enabled && <p className="note">Sending is disabled on this server: download the email and send it from Outlook, then mark it as sent.</p>}
      {letter.send_status === 'failed' && <div role="alert" className="errbox" style={{ marginTop: 8 }}>Last send failed: {letter.send_error}</div>}
      {letter.permissions.approve && letter.transitions.length > 0 && letter.status !== 'Draft' && (
        <div className="filters" style={{ marginTop: 10 }}>
          <div className="f" style={{ flex: '1 1 260px' }}><label htmlFor="bl-note">Status note</label>
            <input id="bl-note" type="text" maxLength={2000} value={note} placeholder="e.g. Sent from Outlook on 18 Nov; BSNL letter no." onChange={(e) => setNote(e.target.value)} /></div>
          {letter.transitions.map((s) => (
            <ConfirmButton key={s} label={STATUS_ACTIONS[s] ?? s} busy={busy} message={`Change the status of ${letter.reference} to "${s}"?`}
              onConfirm={() => action.run(`status-${s}`, async () => { const r = await setLetterStatus(letter.id, s, note); setNote(''); return onChange(r.letter, `Status changed to ${s}.`); })} />
          ))}
        </div>
      )}
      <div style={{ marginTop: 12, overflow: 'auto' }}>
        <div key={`${letter.id}-${letter.updated_at}`} ref={body} className="letter" aria-label="Letter" role="textbox" aria-multiline="true"
          aria-readonly={!editable} contentEditable={editable} suppressContentEditableWarning spellCheck
          onInput={() => setDirty(true)} dangerouslySetInnerHTML={{ __html: letter.html }} />
      </div>
      <div className="tbox" style={{ marginTop: 14 }}><table aria-label="Annexure">
        <thead><tr><th>#</th><th>Site ID</th><th>Cluster</th><th>NE</th><th>Start</th><th>End</th><th className="r">Outage Minutes</th><th>RCA</th><th>Ticket</th></tr></thead>
        <tbody>{letter.annexure.map((r, i) => (
          <tr key={`${r.site_id}-${r.date}-${i}`}><td>{i + 1}</td><td>{r.site_id}</td><td>{r.cluster}</td><td>{r.ne}</td><td>{day(r.start)}</td><td>{day(r.end)}</td>
            <td className="r num">{fmt(r.outage_minutes)}</td><td className="wrap">{r.rca}</td><td>{r.ticket || '–'}</td></tr>
        ))}</tbody></table></div>
      <p className="note" style={{ margin: '6px 0 0' }}>Start and End are the RCA reporting date: the RCA records hold one outage total per site and day, so that day is the period the duration was measured in.</p>
      <details style={{ marginTop: 10 }}><summary>Status history ({letter.events.length})</summary>
        <ul className="note">{letter.events.map((e, i) => (
          <li key={i}>{new Date(e.created_at).toLocaleString('en-IN')} · {e.actor} · {e.action.replaceAll('_', ' ')}{e.status_after && ` → ${e.status_after}`}{e.note && ` · ${e.note}`}</li>
        ))}</ul></details>
    </div>
  );
}

function ProfilesEditor() {
  const [profiles, setProfiles] = useState<CircleProfile[] | null>(null);
  const [canManage, setCanManage] = useState(false);
  const [form, setForm] = useState<CircleProfile | null>(null);
  const action = useAction();
  const load = useCallback((signal?: AbortSignal) => fetchProfiles(signal).then((d) => { setProfiles(d.profiles); setCanManage(d.can_manage); }).catch((cause) => {
    if (!signal?.aborted) action.setError(errorText(cause, 'Circle contacts could not be loaded.'));
  }), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const c = new AbortController(); void load(c.signal); return () => c.abort(); }, [load]);
  const fields: [keyof CircleProfile, string][] = [['bsnl_designation', 'BSNL designation'], ['bsnl_address', 'BSNL address'], ['sender_name', 'Sender name'],
    ['sender_designation', 'Sender designation'], ['company', 'Company']];
  return (
    <div className="card pad">
      <h4>BSNL circle contacts and sender details</h4>
      <Messages error={action.error} notice={action.notice} />
      <div className="tbox"><table aria-label="Circle contacts"><thead><tr><th>Circle</th>{fields.map(([, l]) => <th key={l}>{l}</th>)}<th /></tr></thead>
        <tbody>{(profiles ?? []).map((p) => (
          <tr key={p.circle}><td>{p.name}</td>{fields.map(([k]) => <td key={k} className="wrap">{p[k] || <span className="up-bad">Missing</span>}</td>)}
            <td>{canManage && <button type="button" className="btn sm" onClick={() => setForm({ ...p })}>Edit</button>}</td></tr>
        ))}</tbody></table></div>
      {form && canManage && (
        <form className="grid2" style={{ marginTop: 12 }} aria-label={`Edit ${form.name} contacts`} onSubmit={(e) => {
          e.preventDefault();
          action.run('profile', async () => { await saveProfile(form); await load(); setForm(null); return `${form.name} contacts saved.`; });
        }}>
          {fields.map(([k, l]) => (
            <div key={k} className="f"><label htmlFor={`pf-${k}`}>{l}</label>
              {k === 'bsnl_address'
                ? <textarea id={`pf-${k}`} maxLength={2000} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                : <input id={`pf-${k}`} type="text" maxLength={200} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />}
            </div>
          ))}
          <div className="btns"><button type="submit" className="btn primary" disabled={action.busy !== null}>Save contacts</button>
            <button type="button" className="btn" onClick={() => setForm(null)}>Cancel</button></div>
        </form>
      )}
    </div>
  );
}

function BucketMappingEditor() {
  const [data, setData] = useState<BucketMapping | null>(null);
  const [draft, setDraft] = useState<BucketMapping['mapping']>([]);
  const action = useAction();
  useEffect(() => {
    const c = new AbortController();
    fetchBucketMapping(c.signal).then((d) => { setData(d); setDraft(d.mapping); }).catch((cause) => {
      if (!c.signal.aborted) action.setError(errorText(cause, 'The bucket mapping could not be loaded.'));
    });
    return () => c.abort();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const changed = data ? draft.some((r, i) => r.bucket !== data.mapping[i]?.bucket) : false;
  return (
    <div className="card pad">
      <h4>RCA bucket mapping</h4>
      <p className="note">Approved RCA Final Bucket → responsibility bucket. Customer (BSNL) outages are listed in the letters. {data?.rule}</p>
      <Messages error={action.error} notice={action.notice} />
      <div className="tbox"><table aria-label="RCA bucket mapping"><thead><tr><th>Final Bucket</th><th>Bucket</th></tr></thead>
        <tbody>{draft.map((r, i) => (
          <tr key={r.final_bucket}><td>{r.final_bucket}</td><td>{data?.can_manage
            ? <select aria-label={`Bucket for ${r.final_bucket}`} value={r.bucket} onChange={(e) => setDraft(draft.map((x, j) => (j === i ? { ...x, bucket: e.target.value as typeof x.bucket } : x)))}>
              {data.buckets.map((b) => <option key={b}>{b}</option>)}</select>
            : r.bucket}</td></tr>
        ))}</tbody></table></div>
      {data?.can_manage && (
        <div className="btns" style={{ marginTop: 10 }}>
          <ConfirmButton label="Save mapping" primary busy={action.busy !== null} disabled={!changed} message="Save the bucket mapping? New letters and reports use it immediately."
            onConfirm={() => action.run('map', async () => { const d = await saveBucketMapping(draft); setData(d); setDraft(d.mapping); return 'Bucket mapping saved.'; })} />
        </div>
      )}
    </div>
  );
}

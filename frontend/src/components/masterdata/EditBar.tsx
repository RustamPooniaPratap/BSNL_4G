import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Dialog } from 'radix-ui';
import { Loader2, Plus, Save, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { formatNumber } from '../../lib/format';
import type { DataEdits } from './useDataEdits';

/** The unsaved-changes bar above an editable grid: counts, Add row, Discard and one Save Changes for everything. */
export function EditBar({ edits, canAdd, busy, message, onSave, onDone }: {
  edits: DataEdits; canAdd: boolean; busy: boolean; message: { ok: boolean; text: string } | null; onSave: () => void; onDone: () => void;
}) {
  const parts = [
    edits.cells ? `${formatNumber(edits.cells)} changed cell${edits.cells === 1 ? '' : 's'} in ${formatNumber(edits.rows)} row${edits.rows === 1 ? '' : 's'}` : '',
    edits.additions.length ? `${formatNumber(edits.additions.length)} new row${edits.additions.length === 1 ? '' : 's'}` : '',
  ].filter(Boolean);
  return (
    <div className="space-y-1.5 border-b bg-amber-50/60 px-4 py-2" role="region" aria-label="Unsaved changes">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className={cn('font-medium', edits.dirty ? 'text-amber-900' : 'text-muted-foreground')} aria-live="polite">
          {edits.dirty ? `Unsaved: ${parts.join(' · ')}` : 'Editing: double-click a cell (or select it and type). Changed cells are highlighted until saved.'}
        </span>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {canAdd && <Button size="sm" variant="outline" className="h-7" onClick={edits.addRow} disabled={busy}><Plus /> Add row</Button>}
          <Button size="sm" variant="outline" className="h-7" onClick={edits.discard} disabled={busy || !edits.dirty}><Undo2 /> Discard</Button>
          <Button size="sm" className="h-7" onClick={onSave} disabled={busy || !edits.dirty}>{busy ? <Loader2 className="animate-spin" /> : <Save />} Save Changes</Button>
          <Button size="sm" variant="ghost" className="h-7" onClick={onDone} disabled={busy || edits.dirty} title={edits.dirty ? 'Save or discard the changes first' : undefined}>Done</Button>
        </div>
      </div>
      {message && <p role={message.ok ? 'status' : 'alert'} className={cn('text-xs', message.ok ? 'text-emerald-800' : 'text-destructive')}>{message.text}</p>}
    </div>
  );
}

/**
 * Keeps unsaved Data Panel changes from being lost: ``guard(action)`` runs the action at once when nothing is pending,
 * otherwise asks to save, discard or stay. Links anywhere on the page (tabs, sidebar) and reloading are covered too.
 */
export function useUnsavedGuard(dirty: boolean, save: () => Promise<boolean>, discard: () => void) {
  const [pending, setPending] = useState<(() => void) | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const dirtyRef = useRef(dirty);
  useEffect(() => { dirtyRef.current = dirty; }, [dirty]);

  useEffect(() => {
    if (!dirty) return undefined;
    const beforeUnload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ''; };
    const onClick = (e: globalThis.MouseEvent) => {
      const link = (e.target as HTMLElement | null)?.closest?.('a[href]') as HTMLAnchorElement | null;
      if (!link || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || link.target === '_blank' || link.hasAttribute('download')) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      e.preventDefault();
      e.stopPropagation();
      setPending(() => () => navigate(`${url.pathname}${url.search}${url.hash}`));
    };
    window.addEventListener('beforeunload', beforeUnload);
    document.addEventListener('click', onClick, true);
    return () => { window.removeEventListener('beforeunload', beforeUnload); document.removeEventListener('click', onClick, true); };
  }, [dirty, navigate]);

  const guard = (action: () => void) => { if (dirtyRef.current) setPending(() => action); else action(); };
  const resolve = async (choice: 'save' | 'discard' | 'stay') => {
    const action = pending;
    if (choice === 'stay' || !action) { setPending(null); return; }
    if (choice === 'save') {
      setBusy(true);
      const ok = await save();
      setBusy(false);
      if (!ok) { setPending(null); return; }  // the errors are shown on the cells; stay
    } else discard();
    setPending(null);
    action();
  };
  const dialog = (
    <Dialog.Root open={pending !== null} onOpenChange={(open) => { if (!open && !busy) setPending(null); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(28rem,92vw)] -translate-x-1/2 -translate-y-1/2 space-y-3 rounded-xl border bg-background p-5 shadow-lg">
          <Dialog.Title className="text-base font-semibold">Unsaved changes</Dialog.Title>
          <Dialog.Description className="text-sm text-muted-foreground">
            You have changes that are not saved to the database. Save them, discard them, or stay on this page.
          </Dialog.Description>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => { void resolve('stay'); }} disabled={busy}>Stay</Button>
            <Button variant="outline" onClick={() => { void resolve('discard'); }} disabled={busy}>Discard changes</Button>
            <Button onClick={() => { void resolve('save'); }} disabled={busy}>{busy && <Loader2 className="animate-spin" />}Save and continue</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
  return { guard, dialog };
}

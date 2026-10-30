import { useState, type ReactNode } from 'react';
import { Dialog } from 'radix-ui';
import { Loader2, TriangleAlert, XIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/**
 * Destructive confirmation in the GitHub style: nothing is sent until the Admin types ``phrase`` exactly and confirms.
 * One request per confirmation; the dialog stays open with the server's message if it refuses. The server checks
 * permissions and dependencies again: this dialog is not a security boundary.
 */
export function TypedConfirmDialog({ trigger, triggerLabel, title, children, phrase, action, disabled, error, onConfirm }: {
  trigger: string; triggerLabel: string; title: string; children: ReactNode; phrase: string; action: string; disabled?: boolean;
  /** The server's message after a refused attempt (shown inside the dialog, which stays open). */
  error?: string | null;
  /** Resolves true when the server confirmed the change (the dialog then closes). */
  onConfirm: (reason: string) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const matches = typed === phrase;
  const reset = (next: boolean) => {
    if (busy) return;
    setOpen(next);
    setFailed(false);
    setTyped('');
    setReason('');
  };
  const confirm = async () => {
    if (!matches || busy) return;
    setBusy(true);
    setFailed(false);
    try {
      const done = await onConfirm(reason);
      setFailed(!done);
      if (done) {
        setOpen(false);
        setTyped('');
        setReason('');
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog.Root open={open} onOpenChange={reset}>
      <Dialog.Trigger asChild>
        <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-xs text-destructive hover:text-destructive" disabled={disabled} aria-label={triggerLabel}>
          {trigger}
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-50 flex w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-xl border bg-background p-5 shadow-lg focus:outline-none">
          <div className="flex items-start gap-2">
            <TriangleAlert className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden="true" />
            <Dialog.Title className="flex-1 text-base font-semibold">{title}</Dialog.Title>
            <Dialog.Close className="rounded-sm opacity-70 hover:opacity-100 disabled:pointer-events-none" aria-label="Close" disabled={busy}><XIcon className="size-4" /></Dialog.Close>
          </div>
          <Dialog.Description asChild><div className="text-sm text-muted-foreground">{children}</div></Dialog.Description>
          <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); void confirm(); }}>
            <label className="flex flex-col gap-1.5 text-sm">
              <span>Type <strong className="rounded bg-muted px-1 font-mono">{phrase}</strong> to confirm.</span>
              <Input aria-label={`Type ${phrase} to confirm`} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} disabled={busy} />
            </label>
            <Input aria-label="Reason (optional)" placeholder="Reason (optional, kept in the history)" value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} />
            {failed && error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
            <div className="flex justify-end gap-2">
              <Dialog.Close asChild><Button type="button" variant="ghost" disabled={busy}>Cancel</Button></Dialog.Close>
              <Button type="submit" variant="destructive" disabled={!matches || busy}>{busy && <Loader2 className="animate-spin" />}{action}</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

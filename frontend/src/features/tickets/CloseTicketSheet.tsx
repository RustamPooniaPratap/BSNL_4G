import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { closeTicket } from '../../services/api';
import type { TicketListItem } from '../../types/tickets';

const MAX_REMARKS = 5000;

/**
 * Closure remarks for one Open ticket. Shown only to users the API reports may close the ticket; the API checks the
 * signed-in user's Close permission on the ticket's project and circle again before closing.
 */
export function CloseTicketSheet({ ticket, onCancel, onClosed }: {
  ticket: TicketListItem | null;
  onCancel: () => void;
  onClosed: (ticket: TicketListItem) => void;
}) {
  return (
    <Sheet open={ticket !== null} onOpenChange={(open) => { if (!open) onCancel(); }}>
      <SheetContent className="w-full sm:max-w-md">
        {/* Keyed by ticket so the remarks and error start empty for each ticket. */}
        {ticket && <CloseTicketForm key={ticket.id} ticket={ticket} onCancel={onCancel} onClosed={onClosed} />}
      </SheetContent>
    </Sheet>
  );
}

function CloseTicketForm({ ticket, onCancel, onClosed }: {
  ticket: TicketListItem;
  onCancel: () => void;
  onClosed: (ticket: TicketListItem) => void;
}) {
  const [remarks, setRemarks] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      await closeTicket(ticket.id, remarks.trim());
      onClosed(ticket);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The ticket could not be closed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <SheetHeader>
        <SheetTitle>Close ticket {ticket.portal_ticket_id}</SheetTitle>
        <SheetDescription>{ticket.site_id}{ticket.site_name ? ` · ${ticket.site_name}` : ''} · {ticket.circle}</SheetDescription>
      </SheetHeader>
      <div className="space-y-2 px-4">
        <label htmlFor="ticket-closure-remarks" className="text-sm font-medium">Resolution / closure remarks</label>
        <textarea
          id="ticket-closure-remarks"
          className="min-h-32 w-full rounded-md border bg-background p-2 text-sm"
          maxLength={MAX_REMARKS}
          value={remarks}
          onChange={(event) => setRemarks(event.target.value)}
          placeholder="Describe how the outage was resolved"
        />
        <p className="text-xs text-muted-foreground">Required. Your name and the closure time are recorded in the ticket history.</p>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      </div>
      <SheetFooter className="flex-row justify-end">
        <Button variant="outline" disabled={busy} onClick={onCancel}>Cancel</Button>
        <Button disabled={busy || !remarks.trim()} onClick={submit}>{busy ? 'Closing…' : 'Confirm Close'}</Button>
      </SheetFooter>
    </>
  );
}

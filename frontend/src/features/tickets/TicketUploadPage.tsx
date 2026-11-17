import { useState } from 'react';
import { AlertTriangle, Download, FileSpreadsheet, Upload } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { commitTicketImport, previewTicketImport, ticketTemplateUrl } from '../../services/api';
import type { TicketImportBatch, TicketImportRow } from '../../types/tickets';
import { formatNumber } from '../../lib/format';
import { TicketError, TicketPageFrame } from './TicketPageFrame';

const OUTCOME_LABELS: Record<string, string> = {
  sample_skipped: 'Template example skipped',
  invalid: 'Invalid',
  create: 'New ticket',
  update: 'Updated',
  auto_close: 'Closed',
  reopen: 'Reopened',
  closed_update: 'Updated (closed)',
  closed_skipped: 'Closed row skipped',
};

export function TicketUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<TicketImportBatch | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [acceptInvalid, setAcceptInvalid] = useState(false);
  const [confirmDuplicate, setConfirmDuplicate] = useState(false);

  const preview = async () => {
    if (!file) return;
    setBusy(true);
    setError('');
    setBatch(null);
    setAcceptInvalid(false);
    setConfirmDuplicate(false);
    try {
      setBatch(await previewTicketImport(file));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The workbook could not be validated.');
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!batch) return;
    setBusy(true);
    setError('');
    try {
      setBatch(await commitTicketImport(batch.id, { accept_invalid: acceptInvalid, confirm_duplicate: confirmDuplicate }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The import could not be committed.');
    } finally {
      setBusy(false);
    }
  };

  const counts = batch?.counts;
  const invalidRows = counts?.invalid_rows ?? 0;
  const needsDuplicateConfirmation = !!batch?.duplicate_of && batch.status !== 'committed';
  const needsInvalidConfirmation = invalidRows > 0 && batch?.status !== 'committed';
  const canCommit = batch?.status === 'previewed' && (!needsInvalidConfirmation || acceptInvalid)
    && (!needsDuplicateConfirmation || confirmDuplicate);

  return (
    <TicketPageFrame title="Upload Excel" subtitle="Validate the official workbook, review every row, then confirm ticket updates">
      {error && <TicketError message={error} />}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Upload ticket workbook</CardTitle>
          <CardDescription className="text-xs">Use the official 17-column Ticket_Upload template. Importing is a separate confirmation step; preview alone never changes tickets.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline"><a href={ticketTemplateUrl()}><Download />Download Ticket Template</a></Button>
            <label className="flex h-8 cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm transition-colors hover:bg-muted">
              <FileSpreadsheet className="size-4" />
              <span>{file?.name ?? 'Choose Excel workbook'}</span>
              <input className="sr-only" type="file" accept=".xlsx,.xlsm" onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setBatch(null);
                setError('');
              }} />
            </label>
            <Button onClick={preview} disabled={!file || busy}><Upload />{busy && !batch ? 'Validating…' : 'Validate & Preview'}</Button>
          </div>
          {file && <p className="text-xs text-muted-foreground">{formatNumber(file.size)} bytes selected.</p>}
        </CardContent>
      </Card>

      {batch && (
        <>
          {batch.status === 'committed' ? (
            <Alert>
              <FileSpreadsheet />
              <AlertTitle>Import completed</AlertTitle>
              <AlertDescription>
                {formatNumber(counts?.new_tickets ?? 0)} new; {formatNumber(counts?.existing_tickets_updated ?? 0)} updated;{' '}
                {formatNumber(counts?.tickets_closed ?? 0)} closed; {formatNumber(counts?.tickets_reopened ?? 0)} reopened;{' '}
                {formatNumber(counts?.closed_rows_skipped ?? 0)} closed rows skipped;{' '}
                {formatNumber(counts?.notifications_failed ?? 0)} email(s) failed.
              </AlertDescription>
            </Alert>
          ) : batch.duplicate_of ? (
            <Alert variant="destructive">
              <AlertTriangle />
              <AlertTitle>This exact workbook was imported before</AlertTitle>
              <AlertDescription>Confirm below only if you intend to process the same file again. Existing outages will be updated; repeated Open records send another individual email.</AlertDescription>
            </Alert>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Count label="Rows" value={counts?.total_rows ?? 0} />
            <Count label="Valid rows" value={counts?.valid_rows ?? 0} />
            <Count label="Invalid rows" value={invalidRows} />
            <Count label="Template examples skipped" value={counts?.sample_rows_skipped ?? 0} />
          </div>

          {batch.status !== 'committed' && (needsInvalidConfirmation || needsDuplicateConfirmation) && (
            <Card>
              <CardContent className="space-y-3 pt-4 text-sm">
                {needsInvalidConfirmation && (
                  <label className="flex items-start gap-2">
                    <input type="checkbox" checked={acceptInvalid} onChange={(event) => setAcceptInvalid(event.target.checked)} />
                    <span>Continue with valid rows only; skip the {invalidRows} invalid row(s) shown below.</span>
                  </label>
                )}
                {needsDuplicateConfirmation && (
                  <label className="flex items-start gap-2">
                    <input type="checkbox" checked={confirmDuplicate} onChange={(event) => setConfirmDuplicate(event.target.checked)} />
                    <span>Confirm processing this previously imported workbook again.</span>
                  </label>
                )}
              </CardContent>
            </Card>
          )}

          {batch.status === 'previewed' && (
            <Button onClick={commit} disabled={!canCommit || busy}>
              {busy ? 'Processing…' : 'Create / Update Tickets'}
            </Button>
          )}

          <Card>
            <CardHeader><CardTitle className="text-sm">Row-by-row preview</CardTitle></CardHeader>
            <CardContent className="overflow-x-auto px-0 pt-0">
              <Table className="text-xs">
                <TableHeader><TableRow className="bg-muted/50 hover:bg-muted/50">
                  <TableHead>Excel row</TableHead><TableHead>Site ID</TableHead><TableHead>Site name</TableHead>
                  <TableHead>Date</TableHead><TableHead>TT Status</TableHead><TableHead>Outage Min.</TableHead>
                  <TableHead>MTTR (Hrs.)</TableHead><TableHead>Result</TableHead>
                  <TableHead>Validation</TableHead><TableHead>Portal Ticket ID</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {batch.rows.map((row) => <PreviewRow key={row.excel_row} row={row} />)}
                  {!batch.rows.length && <TableRow><TableCell colSpan={10} className="py-8 text-center text-muted-foreground">No non-blank ticket rows.</TableCell></TableRow>}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </TicketPageFrame>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return <Card><CardContent className="pt-4"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-xl font-semibold tabular-nums">{formatNumber(value)}</p></CardContent></Card>;
}

function PreviewRow({ row }: { row: TicketImportRow }) {
  const status = OUTCOME_LABELS[row.outcome] ?? row.outcome;
  const outageMinutes = row.values?.outage_minutes;
  const mttrHours = row.values?.mttr_hours;
  return (
    <TableRow>
      <TableCell>{row.excel_row}</TableCell>
      <TableCell>{row.source_values['Site ID'] || '—'}</TableCell>
      <TableCell className="whitespace-normal">{row.source_values['Site Name'] || '—'}</TableCell>
      <TableCell>{row.source_values.Date || '—'}</TableCell>
      <TableCell>{row.source_values['TT Status'] || '—'}</TableCell>
      <TableCell>{outageMinutes === undefined || outageMinutes === null || outageMinutes === '' ? '—' : String(outageMinutes)}</TableCell>
      <TableCell>{mttrHours === undefined || mttrHours === null || mttrHours === '' ? '—' : String(mttrHours)}</TableCell>
      <TableCell><Badge variant={row.outcome === 'invalid' ? 'destructive' : row.outcome === 'sample_skipped' ? 'outline' : 'secondary'}>{status}</Badge></TableCell>
      <TableCell className="min-w-60 whitespace-normal">
        {row.errors.length ? <ul className="list-inside list-disc text-destructive">{row.errors.map((item, index) => <li key={`${item.field}-${index}`}><span className="font-medium">{item.field}:</span> {item.message}</li>)}</ul> : '—'}
      </TableCell>
      <TableCell>{row.portal_ticket_id ?? '—'}</TableCell>
    </TableRow>
  );
}

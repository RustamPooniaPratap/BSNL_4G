import { createContext, useContext } from 'react';

/**
 * User-facing wording for the two monthly sources (imported monthly totals / months calculated from daily records).
 * The Overview names the source; the 4G Saturation and LWE pages use neutral wording. Text only: the data is the same.
 */
export interface SourceLabels {
  /** Label of the months from the imported monthly totals (band, tooltips, table, note). */
  history: string;
  /** Tag after a month of that source where both sources are compared (Best / worst tile); '' for none. */
  tag: string;
  /** Short marker of those months in the month picker; null for none. */
  pickerTag: string | null;
  /** Sentence added under the month picker when such months exist. */
  pickerNote: string;
  /** What the note under a chart says about those months. */
  noteDetail: string;
  /** Chart description when both sources are shown (``firstCalculated``: label of the first calculated month). */
  description: (scope: string, firstCalculated: string | undefined) => string;
}

export const SOURCE_LABELS: SourceLabels = {
  history: 'Historical monthly (Excel source)',
  tag: ' (Excel)',
  pickerTag: 'Excel',
  pickerNote: ' Months marked Excel are historical monthly totals (Excel source); period figures cover calculated months only.',
  noteDetail: 'all imported sites with a value; not a population view',
  description: (scope) => `${scope} for the months calculated from daily records; earlier months are the imported historical monthly totals (Excel source), every imported site with a value, outage-weighted.`,
};

export const NEUTRAL_SOURCE_LABELS: SourceLabels = {
  history: 'Monthly reporting data',
  tag: '',
  pickerTag: null,
  pickerNote: ' Period figures cover the months calculated from daily records.',
  noteDetail: 'every site with a value; not a population view',
  description: (scope, first) => `${scope} for the months calculated from daily records${first ? `; months before ${first} show the monthly reporting data` : '; other months show the monthly reporting data'} (every site with a value, outage-weighted).`,
};

export const SourceLabelsContext = createContext<SourceLabels>(SOURCE_LABELS);
export const useSourceLabels = () => useContext(SourceLabelsContext);

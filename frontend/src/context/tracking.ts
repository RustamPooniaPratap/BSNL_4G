import { createContext, useContext } from 'react';
import type { ArrivalRecord, Contact, DeadlineConfig, Deadline, FollowUp } from '../lib/tracking';

/** CSV arrival tracking state, held in browser memory only (lost on refresh; no backend yet). */
export interface TrackingState {
  /** Keyed by submissionKey (report type | circle | reporting date). */
  arrivals: Record<string, ArrivalRecord>;
  /** Keyed by requirementKey (report type | circle). */
  contacts: Record<string, Contact>;
  followUps: FollowUp[];
  deadlines: DeadlineConfig;
  /** O&M Head and Remarks per report type | circle on Site Portfolio (no source in the workbook). */
  portfolioNotes: Record<string, PortfolioNote>;
}

export interface PortfolioNote {
  omHead: string;
  remarks: string;
}

export type TrackingAction =
  | { type: 'saveArrival'; key: string; record: ArrivalRecord; replaceKey?: string }
  | { type: 'removeArrival'; key: string }
  | { type: 'saveContact'; key: string; contact: Contact }
  | { type: 'addFollowUp'; followUp: FollowUp }
  | { type: 'setDeadline'; reportType: string; deadline: Deadline | null }
  | { type: 'saveNote'; key: string; note: PortfolioNote };

export const EMPTY_TRACKING: TrackingState = { arrivals: {}, contacts: {}, followUps: [], deadlines: {}, portfolioNotes: {} };

export function trackingReducer(state: TrackingState, action: TrackingAction): TrackingState {
  switch (action.type) {
    case 'saveArrival': {
      const arrivals = { ...state.arrivals };
      if (action.replaceKey && action.replaceKey !== action.key) delete arrivals[action.replaceKey];
      arrivals[action.key] = action.record;
      return { ...state, arrivals };
    }
    case 'removeArrival': {
      const arrivals = { ...state.arrivals };
      delete arrivals[action.key];
      return { ...state, arrivals };
    }
    case 'saveContact':
      return { ...state, contacts: { ...state.contacts, [action.key]: action.contact } };
    case 'addFollowUp':
      return { ...state, followUps: [...state.followUps, action.followUp] };
    case 'setDeadline':
      return { ...state, deadlines: { ...state.deadlines, [action.reportType]: action.deadline } };
    case 'saveNote':
      return { ...state, portfolioNotes: { ...state.portfolioNotes, [action.key]: action.note } };
    default:
      return state;
  }
}

export interface TrackingContextValue {
  state: TrackingState;
  dispatch: (action: TrackingAction) => void;
}

export const TrackingContext = createContext<TrackingContextValue | null>(null);

export function useTracking(): TrackingContextValue {
  const value = useContext(TrackingContext);
  if (!value) throw new Error('useTracking must be used inside TrackingProvider');
  return value;
}

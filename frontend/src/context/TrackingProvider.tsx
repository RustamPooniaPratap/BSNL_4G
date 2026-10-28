import { useMemo, useReducer, type ReactNode } from 'react';
import { EMPTY_TRACKING, TrackingContext, trackingReducer, type TrackingState } from './tracking';

/**
 * Holds CSV arrival tracking in memory for the whole app session, so moving between pages keeps it.
 * Nothing is written to browser storage or the server: a refresh starts empty again.
 */
export function TrackingProvider({ children, initial = EMPTY_TRACKING }: { children: ReactNode; initial?: TrackingState }) {
  const [state, dispatch] = useReducer(trackingReducer, initial);
  const value = useMemo(() => ({ state, dispatch }), [state]);
  return <TrackingContext.Provider value={value}>{children}</TrackingContext.Provider>;
}

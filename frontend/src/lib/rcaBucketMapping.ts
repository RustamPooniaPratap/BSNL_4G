import { useEffect, useState } from 'react';

const EVENT_NAME = 'rca-bucket-mapping-updated';

/** Notify open portal tabs that responsibility-derived RCA data should be fetched again. */
export function announceRcaBucketMappingUpdate() {
  if (typeof BroadcastChannel === 'undefined') {
    window.dispatchEvent(new Event(EVENT_NAME));
    return;
  }

  const channel = new BroadcastChannel(EVENT_NAME);
  channel.postMessage(null);
  channel.close();
}

export function useRcaBucketMappingRevision() {
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const refresh = () => setRevision((value) => value + 1);
    window.addEventListener(EVENT_NAME, refresh);
    if (typeof BroadcastChannel === 'undefined') {
      return () => window.removeEventListener(EVENT_NAME, refresh);
    }

    const channel = new BroadcastChannel(EVENT_NAME);
    channel.addEventListener('message', refresh);
    return () => {
      window.removeEventListener(EVENT_NAME, refresh);
      channel.removeEventListener('message', refresh);
      channel.close();
    };
  }, []);

  return revision;
}

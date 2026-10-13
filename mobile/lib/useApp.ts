import { useCallback, useEffect, useState } from 'react';
import { AppData, loadApp } from './api';

// Один общий кэш контента на все вкладки: лента и афиша не грузят одно и то же дважды
let cache: AppData | null = null;
let inflight: Promise<AppData> | null = null;
const listeners = new Set<(d: AppData) => void>();

function fetchAll(force = false) {
  if (!force && inflight) return inflight;
  inflight = loadApp().then((d) => { cache = d; listeners.forEach((l) => l(d)); return d; }).finally(() => { inflight = null; });
  return inflight;
}

export function useApp() {
  const [data, setData] = useState<AppData | null>(cache);
  const [error, setError] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    listeners.add(setData);
    if (!cache) fetchAll().catch(() => setError(true));
    return () => { listeners.delete(setData); };
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try { await fetchAll(true); setError(false); } catch { setError(true); } finally { setRefreshing(false); }
  }, []);

  return { data, error, refreshing, refresh };
}

export const findEvent = (key: string) => cache?.events.find((e) => e.key === key);

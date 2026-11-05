import AsyncStorage from '@react-native-async-storage/async-storage';
import { useMemo, useSyncExternalStore } from 'react';
import { useStations } from '@/api/content';
import { km, useProvince } from './province';

// «Моя станция» NS: ближайшая к дому, либо выбранная вручную, либо главный вокзал провинции (если город не указан).
// Ручной выбор привязан к месту жительства: человек переехал и указал новый город — снова берём ближайшую к дому.
export type Station = [code: string, name: string];
const KEY = 'ns_station2';
const MAIN: Record<string, Station> = {
  gr: ['GN', 'Groningen'], fr: ['LW', 'Leeuwarden'], dr: ['ASN', 'Assen'], ov: ['ZL', 'Zwolle'],
  fl: ['ALM', 'Almere Centrum'], ge: ['AH', 'Arnhem Centraal'], ut: ['UT', 'Utrecht Centraal'], nh: ['ASD', 'Amsterdam Centraal'],
  zh: ['RTD', 'Rotterdam Centraal'], ze: ['MDB', 'Middelburg'], nb: ['HT', "'s-Hertogenbosch"], li: ['MT', 'Maastricht'],
};

type Own = { st: Station; home: string };
let own: Own | null = null;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
AsyncStorage.getItem(KEY).then((v) => { try { own = v ? JSON.parse(v) : null; } catch { own = null; } emit(); }).catch(() => {});
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };

/** Выбрать станцию вручную (запоминается для текущего места жительства). */
export function setMyStation(st: Station, home: string) {
  own = { st, home };
  AsyncStorage.setItem(KEY, JSON.stringify(own)).catch(() => {});
  emit();
}

/** Ближайшая станция NS к точке. */
export function nearestStation(lat: number, lon: number, list: Station[], coords: Record<string, [number, number]>) {
  let best: { st: Station; km: number } | null = null;
  for (const s of list) {
    const p = coords[s[0]];
    if (!p) continue;
    const d = km(lat, lon, p[0], p[1]);
    if (!best || d < best.km) best = { st: s, km: d };
  }
  return best;
}

/** Станция человека и откуда она взялась: own — выбрал сам, home — ближайшая к дому, main — вокзал провинции. */
export function useMyStation(): { st: Station; source: 'own' | 'home' | 'main'; km?: number } {
  const { province, home } = useProvince();
  const all = useStations();
  const mine = useSyncExternalStore(subscribe, () => own, () => own);
  const near = useMemo(() => (home && all.data ? nearestStation(home.lat, home.lon, all.data.list, all.data.coords) : null), [home, all.data]);
  if (mine && mine.home === (home?.name || '')) return { st: mine.st, source: 'own' };
  if (near) return { st: near.st, source: 'home', km: near.km };
  return { st: MAIN[province?.id || 'ut'] || MAIN.ut, source: 'main' };
}

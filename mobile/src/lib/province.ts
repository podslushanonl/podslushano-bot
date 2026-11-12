import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSyncExternalStore } from 'react';
import { Province, provinceById, ProvinceId } from './provinces';
import { syncPushProvince } from './push';

// Провинция и место жительства хранятся на устройстве: приложением можно пользоваться без входа.
// Место жительства (город или деревня) уточняет провинцию: по нему выбираются станция, события и места рядом.
// ready — значения уже прочитаны из памяти телефона (до этого не решаем, показывать ли выбор).
export type Home = { name: string; gemeente: string; lat: number; lon: number };

const KEY = 'pn_province';
const HOME = 'pn_home';
let state: { id: ProvinceId | null; home: Home | null; ready: boolean } = { id: null, home: null, ready: false };
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());

const parseHome = (v: string | null): Home | null => {
  try {
    const h = v ? JSON.parse(v) : null;
    return h && typeof h.name === 'string' && typeof h.lat === 'number' && typeof h.lon === 'number' ? h : null;
  } catch { return null; }
};

AsyncStorage.multiGet([KEY, HOME])
  .then(([[, p], [, h]]) => { state = { id: provinceById(p)?.id ?? null, home: parseHome(h), ready: true }; emit(); })
  .catch(() => { state = { ...state, ready: true }; emit(); });

const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
const snap = () => state;

/** Сменить провинцию без города: место жительства из другой провинции сбрасывается. */
export function setProvince(id: ProvinceId) {
  const keepHome = state.id === id ? state.home : null;
  state = { id, home: keepHome, ready: true };
  AsyncStorage.setItem(KEY, id).catch(() => {});
  if (!keepHome) AsyncStorage.removeItem(HOME).catch(() => {});
  emit();
  syncPushProvince(id);
}

/** Место жительства: город или деревня вместе с провинцией. */
export function setHome(home: Home, id: ProvinceId) {
  const changed = state.id !== id;
  state = { id, home, ready: true };
  AsyncStorage.multiSet([[KEY, id], [HOME, JSON.stringify(home)]]).catch(() => {});
  emit();
  if (changed) syncPushProvince(id);
}

// Гостевой режим: пока человек не указал город, показываем столичный регион — контент виден сразу, без вопросов
const DEFAULT = provinceById('nh')!;

/** Текущая провинция (если не выбрана — Noord-Holland и chosen=false), место жительства, готовность хранилища. */
export function useProvince(): { province: Province; chosen: boolean; home: Home | null; ready: boolean } {
  const s = useSyncExternalStore(subscribe, snap, snap);
  return { province: provinceById(s.id) ?? DEFAULT, chosen: !!s.id, home: s.home, ready: s.ready };
}

/** Расстояние в километрах (для «рядом с домом»). */
export function km(aLat: number, aLon: number, bLat: number, bLon: number) {
  const r = Math.PI / 180;
  const x = (bLon - aLon) * r * Math.cos(((aLat + bLat) / 2) * r);
  const y = (bLat - aLat) * r;
  return Math.sqrt(x * x + y * y) * 6371;
}

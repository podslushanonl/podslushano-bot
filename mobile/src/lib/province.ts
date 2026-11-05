import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSyncExternalStore } from 'react';
import { Province, provinceById, ProvinceId } from './provinces';
import { syncPushProvince } from './push';

// Выбранная провинция хранится на устройстве: приложением можно пользоваться без входа.
// ready — значение уже прочитано из памяти телефона (до этого не решаем, показывать ли выбор провинции).
const KEY = 'pn_province';
let state: { id: ProvinceId | null; ready: boolean } = { id: null, ready: false };
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());

AsyncStorage.getItem(KEY)
  .then((v) => { state = { id: provinceById(v)?.id ?? null, ready: true }; emit(); })
  .catch(() => { state = { ...state, ready: true }; emit(); });

const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
const snap = () => state;

/** Сменить провинцию: сохраняется на устройстве, все разделы перестраиваются сразу. */
export function setProvince(id: ProvinceId) {
  state = { id, ready: true };
  AsyncStorage.setItem(KEY, id).catch(() => {});
  emit();
  syncPushProvince(id);
}

/** Текущая провинция (null — ещё не выбрана) и признак, что хранилище прочитано. */
export function useProvince(): { province: Province | null; ready: boolean } {
  const s = useSyncExternalStore(subscribe, snap, snap);
  return { province: provinceById(s.id), ready: s.ready };
}

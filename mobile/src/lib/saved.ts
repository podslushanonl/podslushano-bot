import AsyncStorage from '@react-native-async-storage/async-storage';
import { useSyncExternalStore } from 'react';

// Сохранённые места: хранятся на телефоне, работают без аккаунта.
const KEY = 'pn_saved_places';
let ids: string[] = [];
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
AsyncStorage.getItem(KEY).then((v) => { try { ids = v ? JSON.parse(v) : []; } catch { ids = []; } emit(); }).catch(() => {});

export function useSavedPlaces() {
  return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; }, () => ids, () => ids);
}

/** Сохранить или убрать место. Возвращает новое состояние: true — сохранено. */
export function toggleSavedPlace(id: string): boolean {
  const on = !ids.includes(id);
  ids = on ? [id, ...ids] : ids.filter((x) => x !== id);
  AsyncStorage.setItem(KEY, JSON.stringify(ids)).catch(() => {});
  emit();
  return on;
}

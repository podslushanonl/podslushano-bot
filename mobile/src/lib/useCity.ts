import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useSyncExternalStore } from 'react';
import { saveProfile, useAuth } from '@/api/auth';
import { asCountry, Country } from './countries';

// Город пользователя: из профиля (определён по GPS или выбран в поиске), без входа — выбранный на этом устройстве.
// Списка «крупных городов» больше нет: подходит любой населённый пункт трёх стран.
const KEY = 'pn_city';
let local = '';
const subs = new Set<() => void>();
AsyncStorage.getItem(KEY).then((v) => { if (v) { local = v; subs.forEach((f) => f()); } }).catch(() => {});

/** Страна пользователя из профиля; без входа — Нидерланды. */
export function useCountry(): Country {
  const { user } = useAuth();
  return asCountry(user?.country);
}

/** Город пользователя ('' — ещё не выбран) и смена вручную (координаты при этом сервер сбрасывает). */
export function useCity(): [string, (c: string) => void] {
  const { user } = useAuth();
  const l = useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => local, () => local);
  useEffect(() => { if (user?.city && user.city !== local) { local = user.city; AsyncStorage.setItem(KEY, local).catch(() => {}); subs.forEach((f) => f()); } }, [user?.city]);
  const city = user ? user.city || '' : l;
  const setCity = (c: string) => {
    local = c;
    AsyncStorage.setItem(KEY, c).catch(() => {});
    subs.forEach((f) => f());
    if (user && c !== user.city) saveProfile({ city: c }).catch(() => {});
  };
  return [city, setCity];
}

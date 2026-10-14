import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useSyncExternalStore } from 'react';
import { saveProfile, useAuth } from '@/api/auth';
import { asCountry, CITIES_BY_COUNTRY, Country } from './countries';

// Город пользователя: из профиля, если вошёл, иначе — выбранный на этом устройстве
const KEY = 'pn_city';
let local = '';
const subs = new Set<() => void>();
AsyncStorage.getItem(KEY).then((v) => { if (v) { local = v; subs.forEach((f) => f()); } }).catch(() => {});

export const CITIES = CITIES_BY_COUNTRY['Нидерланды'];

/** Страна пользователя из профиля; без входа — Нидерланды. */
export function useCountry(): Country {
  const { user } = useAuth();
  return asCountry(user?.country);
}

export function useCity(): [string, (c: string) => void] {
  const { user } = useAuth();
  const l = useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => local, () => local);
  useEffect(() => { if (user?.city && !local) { local = user.city; subs.forEach((f) => f()); } }, [user?.city]);
  // Город с устройства подходит, только если он из страны аккаунта (после смены страны старый не тянется)
  const cities = CITIES_BY_COUNTRY[asCountry(user?.country)];
  const city = user?.city || (l && (!user || cities.includes(l)) ? l : '') || cities[0];
  const setCity = (c: string) => {
    local = c;
    AsyncStorage.setItem(KEY, c).catch(() => {});
    subs.forEach((f) => f());
    if (user) saveProfile({ city: c }).catch(() => {});
  };
  return [city, setCity];
}

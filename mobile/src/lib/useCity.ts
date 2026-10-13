import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useSyncExternalStore } from 'react';
import { saveProfile, useAuth } from '@/api/auth';

// Город пользователя: из профиля, если вошёл, иначе — выбранный на этом устройстве
const KEY = 'pn_city';
let local = '';
const subs = new Set<() => void>();
AsyncStorage.getItem(KEY).then((v) => { if (v) { local = v; subs.forEach((f) => f()); } }).catch(() => {});

export const CITIES = ['Amsterdam', 'Rotterdam', 'Den Haag', 'Utrecht', 'Eindhoven', 'Groningen', 'Tilburg', 'Almere', 'Breda',
  'Nijmegen', 'Arnhem', 'Haarlem', 'Leiden', 'Maastricht', 'Zwolle', 'Amersfoort', 'Delft', 'Enschede', 'Den Bosch', 'Oss'];

export function useCity(): [string, (c: string) => void] {
  const { user } = useAuth();
  const l = useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => local, () => local);
  useEffect(() => { if (user?.city && !local) { local = user.city; subs.forEach((f) => f()); } }, [user?.city]);
  const city = user?.city || l || 'Amsterdam';
  const setCity = (c: string) => {
    local = c;
    AsyncStorage.setItem(KEY, c).catch(() => {});
    subs.forEach((f) => f());
    if (user) saveProfile({ city: c }).catch(() => {});
  };
  return [city, setCity];
}

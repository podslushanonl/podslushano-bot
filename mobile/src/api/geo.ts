import { api } from './client';
import { setUser, User } from './auth';

/** Населённый пункт: официальное название латиницей и страна по-русски. */
export type Place = { name: string; country: string; lat?: number; lng?: number };

/** Записать место по координатам: сервер через Google определит город или деревню (только NL, DE, BE). */
export async function saveLocation(lat: number, lng: number): Promise<Place> {
  const d = await api<{ user: User; place: Place }>('/api/app/me/location', { lat, lng });
  setUser(d.user);
  return d.place;
}

/** Поиск населённого пункта по названию — когда GPS выключен или нужен другой город. */
export const searchPlaces = (q: string, country?: string) =>
  api<{ places: Place[] }>(`/api/app/geo/search?q=${encodeURIComponent(q)}${country ? `&country=${encodeURIComponent(country)}` : ''}`)
    .then((d) => d.places);

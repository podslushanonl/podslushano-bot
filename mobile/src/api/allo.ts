import { useQuery } from '@tanstack/react-query';
import { BOT, getJson } from './client';

// Прогулки allo.walks — наши собственные события. Каталог и бронирование — на сервере (utils/allo_v2.py).
export type Walk = {
  key: string; category: 'city' | 'nature' | 'special'; title: string; place: string; meeting: string; duration: string;
  intro: string; starts_at: string; price_cents: number; capacity: number; photos: { url: string; alt: string }[];
  inventory?: { capacity: number; available: number };
};

export const useWalks = () => useQuery({
  queryKey: ['allo', 'walks'], staleTime: 10 * 60_000,
  queryFn: () => getJson<{ events: Walk[] }>(`${BOT}/api/allo/v2/events`).then((d) => d.events || []),
});

/** Страница бронирования прогулок на сервере (оплата — Mollie). Открывается списком всех прогулок. */
export const walkUrl = () => `${BOT}/allo-walks/v2`;

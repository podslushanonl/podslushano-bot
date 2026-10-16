import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Platform } from 'react-native';
import { api, BOT } from './client';
import type { IconName } from '@/ui/Icon';
import { queryClient } from './query';

export type Category = { key: string; title: string; hint: string };
export type Seller = { id: number; name: string; city: string; avatar: string; since: string; verified?: boolean; username?: string };
export type Listing = {
  id: number; cat: string; cat_title: string; title: string;
  /** Цена для показа: «€450», «Бесплатно», «Договорная»; price_value — число евро или null. */
  price: string; price_value: number | null;
  city: string; photo: string; at: string; mine: boolean;
  status: 'active' | 'closed' | 'hidden' | 'removed' | 'expired'; status_title: string;
  description?: string; photos?: string[]; until?: string;
  /** Продавцу можно написать в приложении. */
  chat?: boolean; seller_id?: number; seller?: Seller;
};
export type Page = { items: Listing[]; more: boolean; categories: Category[]; cities: string[] };
export type NewListing = {
  id?: number; category: string; title: string; description: string; price: string; city: string;
  /** Фото по порядку: "keep:<номер>" — оставить уже загруженное, иначе картинка data:... */
  photos: string[];
};

export const photoUrl = (l: Pick<Listing, 'photo'>) => (l.photo ? BOT + l.photo : '');
export const absUrl = (path: string) => (path ? BOT + path : '');
export const MAX_PHOTOS = 5;

/** Категории барахолки (те же ключи на сервере — utils/app_market.py). Иконки — системные, тонкие. */
export const CATEGORIES: (Category & { icon: IconName })[] = [
  { key: 'wardrobe', title: 'Гардероб', hint: 'Одежда, обувь, аксессуары', icon: 'shirt' },
  { key: 'home', title: 'Дом и Уют', hint: 'Мебель, декор, растения, посуда', icon: 'sofa' },
  { key: 'tech', title: 'Техно', hint: 'Гаджеты, Apple, приставки, электроника', icon: 'devices' },
  { key: 'sport', title: 'Спорт и Байки', hint: 'Велосипеды, самокаты, экипировка', icon: 'bike' },
  { key: 'tickets', title: 'Билеты', hint: 'Концерты, фестивали, события', icon: 'ticket' },
  { key: 'housing', title: 'Жилье', hint: 'Аренда комнат, квартир, субаренда', icon: 'house' },
  { key: 'services', title: 'Услуги', hint: 'Локальные мастера, хелперы, репетиторы', icon: 'wrench' },
  { key: 'free', title: 'Даром', hint: 'Вещи за самовывоз, бесплатно', icon: 'gift' },
];
export const CAT_ICON: Record<string, IconName> = Object.fromEntries(CATEGORIES.map((c) => [c.key, c.icon]));
/** Города в форме подачи; остальные — через «Другой город». */

export type MarketFilter = { cat: string; city: string; q: string };

export function useMarket(f: MarketFilter) {
  return useInfiniteQuery({
    queryKey: ['market', f],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams();
      if (f.cat) qs.set('cat', f.cat);
      if (f.city) qs.set('city', f.city);
      if (f.q) qs.set('q', f.q);
      if (pageParam) qs.set('offset', String(pageParam));
      return api<Page>(`/api/app/market?${qs}`);
    },
    getNextPageParam: (last, all) => (last.more ? all.reduce((n, p) => n + p.items.length, 0) : undefined),
    staleTime: 30_000,
  });
}

/** Активные объявления одного продавца — вкладка «Барахолка» в профиле. */
export const useUserListings = (userId: number, enabled = true) => useQuery({
  queryKey: ['market', 'user', userId], enabled: enabled && userId > 0, staleTime: 30_000,
  queryFn: () => api<Page>(`/api/app/market?user=${userId}`).then((d) => d.items),
});
export const useListing = (id: number) => useQuery({ queryKey: ['listing', id], enabled: id > 0, queryFn: () => api<{ item: Listing }>(`/api/app/market/${id}`).then((d) => d.item) });
export const useMyListings = (enabled: boolean) => useQuery({ queryKey: ['me', 'listings'], enabled, queryFn: () => api<{ items: Listing[]; max: number }>('/api/app/market/my') });

export const submitListing = (l: NewListing) => api<{ id: number; status: string }>('/api/app/market', l);
export const closeListing = (id: number) => api(`/api/app/market/${id}/close`, {});
export const reportListing = (id: number, reason: string) => api(`/api/app/market/${id}/report`, { reason });

export const marketChanged = () => {
  queryClient.invalidateQueries({ queryKey: ['market'] });
  queryClient.invalidateQueries({ queryKey: ['me', 'listings'] });
  queryClient.invalidateQueries({ queryKey: ['listing'] });
};

export const REPORT_REASONS: [string, string][] = [
  ['scam', 'Похоже на мошенничество'], ['outdated', 'Уже не актуально'], ['duplicate', 'Дубликат'],
  ['prohibited', 'Запрещённый контент'], ['other', 'Другая причина'],
];

/** В браузере фото с телефона бывает 10+ МБ: уменьшаем до 1600 px перед отправкой. */
export async function shrinkForWeb(uri: string): Promise<string> {
  if (Platform.OS !== 'web') return uri;
  const img = new (globalThis as any).Image();
  img.src = uri;
  await img.decode();
  const k = Math.min(1, 1600 / Math.max(img.width, img.height));
  const canvas = (globalThis as any).document.createElement('canvas');
  canvas.width = Math.round(img.width * k);
  canvas.height = Math.round(img.height * k);
  canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.85);
}

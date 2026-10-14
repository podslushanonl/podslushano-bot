import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Platform } from 'react-native';
import { api, BOT } from './client';
import { queryClient } from './query';

export type Intent = { key: string; title: string };
export type Category = { key: string; title: string; intents: Intent[] };
export type Contact = { type: string; title: string; url: string };
export type ContactForm = Partial<Record<'telegram' | 'whatsapp' | 'phone' | 'email' | 'instagram', string>>;
export type Listing = {
  id: number; cat: string; cat_title: string; intent: string; intent_title: string;
  title: string; price: string; city: string; photo: string; at: string; mine: boolean;
  status?: string; status_title?: string;
  /** Продавцу можно написать в приложении (он сам подавал объявление через приложение). */
  chat?: boolean;
  /** Аккаунт продавца в приложении: личка открывается, когда вы друзья. */
  seller_id?: number;
  description?: string; contacts?: Contact[]; until?: string; photos?: string[];
  form?: { city: string; nationwide: boolean; contacts: ContactForm };
};
export type Page = { items: Listing[]; more: boolean; categories: Category[]; cities: string[] };
export type NewListing = {
  id?: number; category: string; intent: string; title: string; description: string; price: string;
  city: string; nationwide: boolean; contacts: ContactForm;
  /** Фото по порядку: "keep:<номер>" — оставить уже загруженное, иначе картинка data:... */
  photos: string[];
};

export const photoUrl = (l: Pick<Listing, 'photo'>) => (l.photo ? BOT + l.photo : '');
export const absUrl = (path: string) => (path ? BOT + path : '');
export const MAX_PHOTOS = 8;

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

/** Категории и города для фильтров и формы (берутся из первой страницы барахолки). */
export const useMarketMeta = () => useQuery({
  queryKey: ['market-meta'], staleTime: 3600_000,
  queryFn: () => api<Page>('/api/app/market?offset=0').then((d) => ({ categories: d.categories, cities: d.cities })),
});
export const useListing = (id: number) => useQuery({ queryKey: ['listing', id], enabled: id > 0, queryFn: () => api<{ item: Listing }>(`/api/app/market/${id}`).then((d) => d.item) });
export const useMyListings = (enabled: boolean) => useQuery({ queryKey: ['me', 'listings'], enabled, queryFn: () => api<{ items: Listing[]; max: number }>('/api/app/market/my') });

export const submitListing = (l: NewListing) =>
  api<{ id: number; status: string; pay_url?: string; price?: string; pay_error?: string }>('/api/app/market', l);
export const payListing = (id: number) => api<{ pay_url: string }>(`/api/app/market/${id}/pay`, {});
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

export const CAT_ICON: Record<string, 'house' | 'market' | 'gift' | 'briefcase' | 'car' | 'box'> = {
  housing: 'house', goods: 'market', free: 'gift', jobs: 'briefcase', rides: 'car', other: 'box',
};

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

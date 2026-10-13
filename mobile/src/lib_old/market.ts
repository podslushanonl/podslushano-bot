import { Platform } from 'react-native';
import { BOT } from './api';
import { call } from './auth';

export type Intent = { key: string; title: string };
export type Category = { key: string; title: string; intents: Intent[] };
export type Contact = { type: string; title: string; url: string };
export type ContactForm = Partial<Record<'telegram' | 'whatsapp' | 'phone' | 'email' | 'instagram', string>>;
export type Listing = {
  id: number; cat: string; cat_title: string; intent: string; intent_title: string;
  title: string; price: string; city: string; photo: string; at: string; mine: boolean;
  status?: string; status_title?: string;
  description?: string; contacts?: Contact[]; until?: string;
  form?: { city: string; nationwide: boolean; contacts: ContactForm };
};
export type Page = { items: Listing[]; more: boolean; categories: Category[]; cities: string[] };
export type NewListing = {
  id?: number; category: string; intent: string; title: string; description: string; price: string;
  city: string; nationwide: boolean; contacts: ContactForm; photo?: string;
};

export const photoUrl = (l: Listing) => (l.photo ? BOT + l.photo : '');

export function browse(p: { cat?: string; city?: string; q?: string; offset?: number }) {
  const qs = new URLSearchParams();
  if (p.cat) qs.set('cat', p.cat);
  if (p.city) qs.set('city', p.city);
  if (p.q) qs.set('q', p.q);
  if (p.offset) qs.set('offset', String(p.offset));
  return call<Page>(`/api/app/market?${qs}`);
}
export const getListing = (id: number) => call<{ item: Listing }>(`/api/app/market/${id}`).then((d) => d.item);
export const myListings = () => call<{ items: Listing[]; max: number }>('/api/app/market/my');
export const submitListing = (l: NewListing) =>
  call<{ id: number; status: string; pay_url?: string; price?: string; pay_error?: string }>('/api/app/market', l);
export const payListing = (id: number) => call<{ pay_url: string }>(`/api/app/market/${id}/pay`, {});
export const closeListing = (id: number) => call(`/api/app/market/${id}/close`, {});
export const reportListing = (id: number, reason: string) => call(`/api/app/market/${id}/report`, { reason });

export const REPORT_REASONS: [string, string][] = [
  ['scam', 'Похоже на мошенничество'], ['outdated', 'Уже не актуально'], ['duplicate', 'Дубликат'],
  ['prohibited', 'Запрещённый контент'], ['other', 'Другая причина'],
];

// После подачи или снятия объявления списки обновляются сами
const listeners = new Set<() => void>();
export const notifyMarketChanged = () => listeners.forEach((l) => l());
export function onMarketChanged(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }

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

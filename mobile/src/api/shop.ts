import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQuery } from '@tanstack/react-query';
import { useSyncExternalStore } from 'react';
import { api, BOT, getJson, mediaUrl } from './client';

// Магазин мерча podslushano.nl (сервер: utils/shop.py). Шопперы печатаются под каждый заказ.
export type Product = { id: string; title: string; price: string; text?: string; colors?: string[]; images?: string[]; available?: boolean };
export type Country = 'NL' | 'DE' | 'BE';
export type Catalog = { open: boolean; currency: string; shipping: Record<Country, string>; countries: Record<Country, string>; products: Product[] };
export type OrderItem = { id: string; title: string; color: string; qty: number; price: string };
export type Order = {
  code: string; token: string; status: 'new' | 'paid' | 'printing' | 'shipped' | 'failed' | 'canceled'; status_ru: string;
  items: OrderItem[]; subtotal: string; shipping: string; total: string; name: string; address: string; tracking: string; created_at: string;
};

/** «24.95» → «€24,95» */
export const euro = (v: string | number) => `€${Number(v).toFixed(2).replace('.', ',')}`;

export const useCatalog = () => useQuery({
  queryKey: ['shop', 'catalog'], staleTime: 10 * 60_000,
  // путь к фото без домена («/shop-img/…») дополняем адресом сервера
  queryFn: () => getJson<Catalog>(`${BOT}/api/shop/catalog`)
    .then((c) => ({ ...c, products: c.products.map((p) => ({ ...p, images: (p.images || []).map(mediaUrl) })) })),
});

export const useOrder = (token: string) => useQuery({
  queryKey: ['shop', 'order', token], enabled: !!token,
  queryFn: () => getJson<{ order: Order }>(`${BOT}/api/shop/order/${token}`).then((d) => d.order),
  // пока заказ ждёт оплаты, проверяем статус каждые 4 секунды: webhook Mollie приходит не мгновенно
  refetchInterval: (q) => (q.state.data?.status === 'new' ? 4000 : false),
});

export type Address = { country: Country; name: string; email: string; phone: string; street: string; house: string; postcode: string; city: string };

export async function createOrder(items: CartLine[], a: Address) {
  const d = await api<{ token: string; code: string; checkout_url: string }>('/api/shop/order', {
    ...a, items: items.map((i) => ({ id: i.id, color: i.color, qty: i.qty })),
  });
  rememberOrder(d.token);
  return d;
}

// ---------------------------------------------------------------- корзина (на устройстве)

export type CartLine = { id: string; color: string; qty: number };
const CART = 'pn_cart';
const ORDERS = 'pn_orders';
let cart: CartLine[] = [];
let orders: string[] = [];
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
AsyncStorage.multiGet([CART, ORDERS]).then(([[, c], [, o]]) => {
  try { cart = c ? JSON.parse(c) : []; orders = o ? JSON.parse(o) : []; } catch { cart = []; orders = []; }
  emit();
}).catch(() => {});

const save = () => { AsyncStorage.setItem(CART, JSON.stringify(cart)).catch(() => {}); emit(); };
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };

export function useCart() {
  return useSyncExternalStore(subscribe, () => cart, () => cart);
}
export function useMyOrders() {
  return useSyncExternalStore(subscribe, () => orders, () => orders);
}

export function addToCart(id: string, color: string, qty = 1) {
  const i = cart.findIndex((l) => l.id === id && l.color === color);
  cart = i >= 0 ? cart.map((l, j) => (j === i ? { ...l, qty: Math.min(10, l.qty + qty) } : l)) : [...cart, { id, color, qty }];
  save();
}
export function setQty(id: string, color: string, qty: number) {
  cart = qty <= 0 ? cart.filter((l) => !(l.id === id && l.color === color))
    : cart.map((l) => (l.id === id && l.color === color ? { ...l, qty: Math.min(10, qty) } : l));
  save();
}
export function clearCart() { cart = []; save(); }

function rememberOrder(token: string) {
  orders = [token, ...orders.filter((t) => t !== token)].slice(0, 20);
  AsyncStorage.setItem(ORDERS, JSON.stringify(orders)).catch(() => {});
  emit();
}

// ---------------------------------------------------------------- лист ожидания (пока продажи закрыты)

export const useWaitlist = () => useQuery({
  queryKey: ['shop', 'waitlist'], staleTime: 60_000,
  queryFn: () => getJson<{ count: number }>(`${BOT}/api/waitlist/shoppers`).then((d) => d.count || 0),
});

/** Запись в лист ожидания шопперов: письмо придёт в день старта продаж. Возвращает номер в списке. */
export async function joinWaitlist(email: string, productId: string) {
  return api<{ position: number; already: boolean; count: number }>('/api/waitlist/shoppers/join', {
    email: email.trim(), consent: '1', source: `app:${productId}`.slice(0, 40),
  });
}

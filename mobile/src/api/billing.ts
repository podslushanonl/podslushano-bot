import { useQuery } from '@tanstack/react-query';
import { api } from './client';
import { setUser, User } from './auth';
import { queryClient } from './query';

/** «Премиум верификация»: статус галочки, цена и готова ли оплата. */
export type VerifyStatus = {
  verified: boolean; until: string; lifetime: boolean; price: number; currency: string; available: boolean; mock: boolean;
};
const KEY = ['me', 'billing', 'verify'];

export const useVerifyStatus = (enabled: boolean) => useQuery({
  queryKey: KEY, enabled, staleTime: 10_000, queryFn: () => api<VerifyStatus>('/api/app/billing/verify'),
});

/** Начать оплату: {url} страницы оплаты Stripe или сразу {paid} (проверочный режим). */
export async function startVerify(): Promise<{ url?: string; paid?: boolean }> {
  const d = await api<{ url?: string; paid?: boolean; user?: User }>('/api/app/billing/verify', {});
  if (d.user) setUser(d.user);
  queryClient.invalidateQueries({ queryKey: KEY });
  return d;
}

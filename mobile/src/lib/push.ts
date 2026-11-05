import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { useSyncExternalStore } from 'react';
import { Platform } from 'react-native';
import { api } from '@/api/client';

// Push-уведомления (сервер: utils/push.py, utils/app_alerts.py): утренняя сводка по провинции и сбои на своей станции.
// Включаются только по действию человека; токен хранится на телефоне, чтобы при смене
// провинции перерегистрироваться, а при выключении — отписаться.
const KEY = 'pn_push_token';
const PREFS = 'pn_push_prefs';
export type PushPrefs = { morning: boolean; trains: boolean };
let token: string | null = null;
let prefs: PushPrefs = { morning: true, trains: true };
// Последнее, что знаем о человеке: провинция и станция (для сбоев на ней). Обновляет usePushSync.
let ctx: { province: string; station: string; stationName: string } = { province: '', station: '', stationName: '' };
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
AsyncStorage.multiGet([KEY, PREFS]).then(([[, t], [, p]]) => {
  token = t;
  try { if (p) prefs = { ...prefs, ...JSON.parse(p) }; } catch { /* по умолчанию всё включено */ }
  emit();
}).catch(() => {});

const body = (t: string) => ({
  token: t, province: ctx.province, platform: Platform.OS, station: ctx.station, station_name: ctx.stationName,
  morning: prefs.morning, trains: prefs.trains,
});
// Регистрации идут по одной: если данные изменились, пока запрос в пути, следом уходит ещё один —
// с самыми свежими провинцией, станцией и выбором. Старый запрос не может перезаписать новый.
let inflight: Promise<void> | null = null;
let again = false;
function register(t: string): Promise<void> {
  if (inflight) { again = true; return inflight; }
  const run = async (): Promise<void> => {
    try {
      await api('/api/app/push/register', body(t));
    } finally {
      if (again && token) { again = false; await run(); }
    }
  };
  inflight = run().finally(() => { inflight = null; });
  return inflight;
}

export const pushSupported = Platform.OS !== 'web';

/** Уведомления в приложении: показывать баннер, когда приложение открыто. */
export function setupNotifications() {
  if (!pushSupported) return;
  Notifications.setNotificationHandler({
    handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false }),
  });
}

const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
export function usePushEnabled() {
  return useSyncExternalStore(subscribe, () => !!token, () => !!token);
}
export function usePushPrefs() {
  return useSyncExternalStore(subscribe, () => prefs, () => prefs);
}

/** Какие уведомления получать: утренняя сводка, сбои на своей станции. Сразу сообщаем серверу. */
export async function setPushPrefs(next: Partial<PushPrefs>) {
  const before = prefs;
  prefs = { ...prefs, ...next };
  emit();
  try {
    if (token) await register(token);
  } catch (e) {
    // Сервер не узнал о выборе — возвращаем переключатель, чтобы он не обещал того, чего нет
    prefs = before;
    emit();
    throw e;
  }
  await AsyncStorage.setItem(PREFS, JSON.stringify(prefs)).catch(() => {});
}

/** Провинция или станция изменились: если уведомления включены, обновить данные на сервере. */
export function syncPushContext(next: typeof ctx) {
  const changed = next.province !== ctx.province || next.station !== ctx.station;
  ctx = next;
  if (changed && token && ctx.province) register(token).catch(() => {});
}

export class PushError extends Error {}

/** Включить уведомления для провинции: разрешение → токен Expo → регистрация на сервере. */
export async function enablePush(province: string) {
  if (!pushSupported) throw new PushError('Уведомления работают в приложении на телефоне.');
  if (!Device.isDevice) throw new PushError('Уведомления работают только на настоящем телефоне.');
  if (Platform.OS === 'android') {
    // На Android 13+ без канала система не покажет запрос разрешения и не выдаст токен
    await Notifications.setNotificationChannelAsync('default', { name: 'События и новости провинции', importance: Notifications.AndroidImportance.DEFAULT });
  }
  const perm = await Notifications.requestPermissionsAsync();
  const granted = perm.granted || perm.ios?.status === Notifications.IosAuthorizationStatus.PROVISIONAL;
  if (!granted) throw new PushError('Уведомления запрещены. Разрешите их в настройках телефона.');
  const projectId = Constants?.expoConfig?.extra?.eas?.projectId ?? Constants?.easConfig?.projectId;
  const t = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
  ctx = { ...ctx, province };
  await register(t);
  token = t;
  await AsyncStorage.setItem(KEY, t).catch(() => {});
  emit();
}

export async function disablePush() {
  const t = token;
  token = null;
  emit();
  await AsyncStorage.removeItem(KEY).catch(() => {});
  if (t) await api('/api/app/push/unregister', { token: t }).catch(() => {});
}

/** Провинция сменилась: если уведомления включены, перерегистрироваться с новой. */
export function syncPushProvince(province: string) {
  syncPushContext({ ...ctx, province });
}

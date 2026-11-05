import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { useSyncExternalStore } from 'react';
import { Platform } from 'react-native';
import { api } from '@/api/client';

// Push-уведомления по выбранной провинции (сервер: utils/push.py).
// Включаются только по действию человека; токен хранится на телефоне, чтобы при смене
// провинции перерегистрироваться, а при выключении — отписаться.
const KEY = 'pn_push_token';
let token: string | null = null;
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
AsyncStorage.getItem(KEY).then((v) => { token = v; emit(); }).catch(() => {});

export const pushSupported = Platform.OS !== 'web';

/** Уведомления в приложении: показывать баннер, когда приложение открыто. */
export function setupNotifications() {
  if (!pushSupported) return;
  Notifications.setNotificationHandler({
    handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false }),
  });
}

export function usePushEnabled() {
  return useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; }, () => !!token, () => !!token);
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
  await api('/api/app/push/register', { token: t, province, platform: Platform.OS });
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
  if (token) api('/api/app/push/register', { token, province, platform: Platform.OS }).catch(() => {});
}

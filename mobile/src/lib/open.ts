import * as WebBrowser from 'expo-web-browser';
import { Linking, Platform } from 'react-native';
import { TG_BOT } from '@/api/client';

/** Ссылка на сайт или партнёра — во встроенном браузере; tel:, mailto:, t.me — в системном приложении. */
export function openUrl(url: string) {
  if (!url) return;
  if (/^(tel:|mailto:|https:\/\/t\.me\/|https:\/\/wa\.me\/)/.test(url)) {
    if (Platform.OS === 'web') { (globalThis as any).open(url, '_blank', 'noopener'); return; }
    Linking.openURL(url).catch(() => {});
    return;
  }
  WebBrowser.openBrowserAsync(url, { presentationStyle: WebBrowser.WebBrowserPresentationStyle.PAGE_SHEET }).catch(() => Linking.openURL(url));
}

export const openBot = (start?: string) => openUrl(start ? `${TG_BOT}?start=${start}` : TG_BOT);

import { Linking, Platform } from 'react-native';

/** Маршрут до точки: на iPhone — Apple Maps, на Android и в браузере — Google Maps. */
export function openRoute(lat: number, lon: number, name: string) {
  const q = encodeURIComponent(name);
  const url = Platform.OS === 'ios'
    ? `maps://?daddr=${lat},${lon}&q=${q}`
    : `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`;
  if (Platform.OS === 'web') { (globalThis as any).open(url, '_blank', 'noopener'); return; }
  Linking.openURL(url).catch(() => Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`));
}

/** Маршрут по адресу (когда координат нет): поиск места в картах. */
export function openRouteTo(address: string) {
  const q = encodeURIComponent(address);
  const url = Platform.OS === 'ios' ? `maps://?daddr=${q}` : `https://www.google.com/maps/dir/?api=1&destination=${q}`;
  if (Platform.OS === 'web') { (globalThis as any).open(url, '_blank', 'noopener'); return; }
  Linking.openURL(url).catch(() => Linking.openURL(`https://www.google.com/maps/dir/?api=1&destination=${q}`));
}

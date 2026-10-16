import * as ImagePicker from 'expo-image-picker';
import * as Location from 'expo-location';
import { Platform } from 'react-native';
import { Place, saveLocation } from '@/api/geo';

export class LocationDenied extends Error {}

/** GPS: системный запрос разрешения → координаты → населённый пункт на сервере (Google). */
export async function locateMe(): Promise<Place> {
  const perm = await Location.requestForegroundPermissionsAsync();
  if (!perm.granted) throw new LocationDenied('Разрешите доступ к геолокации в настройках телефона или выберите город вручную.');
  const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
  return saveLocation(pos.coords.latitude, pos.coords.longitude);
}

/** Разрешено ли уже (без вопроса): чтобы молча обновлять место при запуске. */
export async function locationGranted() {
  try { return (await Location.getForegroundPermissionsAsync()).granted; } catch { return false; }
}

/** Камера и микрофон: в браузере — один системный запрос на оба, в приложении — камера (микрофон iOS спросит при записи видео). */
export async function askCameraAndMic(): Promise<boolean> {
  if (Platform.OS === 'web') {
    const md = (globalThis as any).navigator?.mediaDevices;
    if (!md?.getUserMedia) return false;
    try {
      const stream = await md.getUserMedia({ video: true, audio: true });
      stream.getTracks().forEach((t: any) => t.stop());
      return true;
    } catch { return false; }
  }
  return (await ImagePicker.requestCameraPermissionsAsync()).granted;
}

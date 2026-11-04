import { Platform } from 'react-native';

/** В браузере сжимает фото до 1600 px по длинной стороне (JPEG), на телефоне возвращает адрес как есть. */
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

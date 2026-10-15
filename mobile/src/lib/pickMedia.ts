import * as ImagePicker from 'expo-image-picker';

export type PickedFile = { uri: string; name: string; type: string; kind: 'photo' | 'video' };

/** Выбор фото или видео из галереи для загрузки формой (сторис, Pulse). null — человек передумал. */
export async function pickMedia(kinds: ('images' | 'videos')[], maxSeconds = 60): Promise<PickedFile | null> {
  const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: kinds, quality: 0.85, videoMaxDuration: maxSeconds,
    allowsMultipleSelection: false });
  const a = r.canceled ? null : r.assets?.[0];
  if (!a) return null;
  const video = a.type === 'video' || (a.mimeType || '').startsWith('video/');
  const type = a.mimeType || (video ? 'video/mp4' : 'image/jpeg');
  const ext = type.split('/')[1]?.replace('quicktime', 'mov').replace('jpeg', 'jpg') || (video ? 'mp4' : 'jpg');
  return { uri: a.uri, name: a.fileName || `upload.${ext}`, type, kind: video ? 'video' : 'photo' };
}

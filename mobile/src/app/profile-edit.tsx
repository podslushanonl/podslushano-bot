import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';
import { saveAvatar, saveProfile, useAuth } from '@/api/auth';
import { AvatarCropper, Crop } from '@/features/profile/AvatarCropper';
import { shrinkForWeb } from '@/lib/image';
import { useTheme } from '@/theme';
import { Avatar, Button, Field, Icon, PageScreen, Tap, Txt, useToast } from '@/ui';

const MAX_UPLOAD = 9_000_000;   // символов base64: сервер принимает запрос до 10 МБ

/** Имя и фото аккаунта. Больше о человеке приложению знать не нужно. */
export default function ProfileEdit() {
  const { user } = useAuth();
  const toast = useToast();
  const { c } = useTheme();
  const [name, setName] = useState(user?.name || '');
  const [photoBusy, setPhotoBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  // Открыли экран раньше, чем загрузился аккаунт, — подставляем имя, когда он придёт
  const filled = useRef(!!user);
  useEffect(() => {
    if (!user || filled.current) return;
    filled.current = true;
    setName(user.name || '');
  }, [user]);

  // Фото выбираем без системной обрезки: рамку человек выставляет сам в нашем кадрировании
  const [pick, setPick] = useState<{ uri: string; data: string } | null>(null);
  const pickPhoto = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.5, base64: true });
    if (r.canceled || !r.assets?.length) return;
    const a = r.assets[0];
    const data = a.base64 ? `data:${a.mimeType || 'image/jpeg'};base64,${a.base64}` : await shrinkForWeb(a.uri);
    if (data.length > MAX_UPLOAD) { toast('Фото слишком большое. Выберите другое.', 'error'); return; }
    setPick({ uri: Platform.OS === 'web' ? data : a.uri, data });
  };
  const upload = async (crop: Crop) => {
    if (!pick) return;
    const data = pick.data;
    setPick(null);
    setPhotoBusy(true);
    try {
      await saveAvatar(data, crop);
      toast('Фото обновлено');
    } catch (e: any) { toast(e?.message || 'Фото не загрузилось. Попробуйте ещё раз.', 'error'); } finally { setPhotoBusy(false); }
  };
  const save = async () => {
    setBusy(true); setErr('');
    try {
      await saveProfile({ name: name.trim() });
      toast('Сохранено');
      if (router.canGoBack()) router.back(); else router.replace('/profile');
    } catch (e: any) { setErr(e?.message || 'Не сохранилось. Попробуйте ещё раз.'); } finally { setBusy(false); }
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen title="Имя и фото" footer={<Button title="Сохранить" kind="accent" loading={busy} disabled={name.trim().length < 2} onPress={save} />}>
        <View style={{ alignItems: 'center', gap: 10 }}>
          <Tap onPress={pickPhoto} disabled={photoBusy} scaleTo={0.95} accessibilityLabel="Изменить фото профиля">
            <Avatar name={name || user?.name || '·'} id={user?.id} uri={user?.avatar} size={104} />
            <View style={{ position: 'absolute', right: 0, bottom: 0, width: 34, height: 34, borderRadius: 17, backgroundColor: c.accent,
              alignItems: 'center', justifyContent: 'center', borderWidth: 3, borderColor: c.bg }}>
              <Icon name="camera" size={16} color={c.onAccent} />
            </View>
          </Tap>
          <Tap onPress={pickPhoto} disabled={photoBusy}>
            <Txt v="subhead" tone="accent" style={{ fontWeight: '600' }}>{photoBusy ? 'Загружаем…' : user?.avatar ? 'Изменить фото' : 'Добавить фото'}</Txt>
          </Tap>
          {user?.avatar ? <Tap onPress={() => saveAvatar('').then(() => toast('Фото убрано'))}><Txt v="footnote">Убрать фото</Txt></Tap> : null}
        </View>
        <Txt v="title1" accessibilityRole="header">{user?.name ? 'Имя и фото' : 'Как вас зовут?'}</Txt>
        <Field label="Имя" value={name} onChangeText={setName} maxLength={80} placeholder="Анна" autoComplete="given-name" textContentType="givenName" />
        {err ? <Txt v="callout" tone="danger">{err}</Txt> : null}
      </PageScreen>
      <AvatarCropper uri={pick?.uri ?? null} onDone={upload} onCancel={() => setPick(null)} />
    </KeyboardAvoidingView>
  );
}

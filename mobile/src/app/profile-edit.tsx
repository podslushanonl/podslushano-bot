import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';
import { saveAvatar, saveProfile, useAuth } from '@/api/auth';
import { shrinkForWeb } from '@/api/market';
import { CitySheet } from '@/features/common/CitySheet';
import { AvatarCropper, Crop } from '@/features/profile/AvatarCropper';
import { asCountry, CITIES_BY_COUNTRY, COUNTRIES, Country } from '@/lib/countries';
import { useTheme } from '@/theme';
import { Avatar, Button, Chip, Field, Icon, PageScreen, Tap, Txt, useToast } from '@/ui';

export default function ProfileEdit() {
  const { user } = useAuth();
  const toast = useToast();
  const { c } = useTheme();
  const [name, setName] = useState(user?.name || '');
  const [bio, setBio] = useState(user?.bio || '');
  const [photoBusy, setPhotoBusy] = useState(false);
  const [country, setCountry] = useState<Country>(asCountry(user?.country));
  const [city, setCity] = useState(user?.city || '');
  const [picker, setPicker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  // Открыли экран раньше, чем загрузился аккаунт, — подставляем данные, когда он придёт
  const filled = useRef(!!user);
  useEffect(() => {
    if (!user || filled.current) return;
    filled.current = true;
    setName(user.name || ''); setCountry(asCountry(user.country)); setCity(user.city || ''); setBio(user.bio || '');
  }, [user]);
  const pickCountry = (c: Country) => {
    setCountry(c);
    if (city && !CITIES_BY_COUNTRY[c].includes(city)) setCity('');   // город из другой страны сбрасываем
  };
  // Фото выбираем без системной обрезки: рамку человек выставляет сам в нашем кадрировании
  const [pick, setPick] = useState<{ uri: string; data: string } | null>(null);
  const pickPhoto = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.85, base64: true });
    if (r.canceled || !r.assets?.length) return;
    const a = r.assets[0];
    const data = a.base64 ? `data:${a.mimeType || 'image/jpeg'};base64,${a.base64}` : await shrinkForWeb(a.uri);
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
    } catch (e: any) { toast(e?.message || 'Не загрузилось', 'error'); } finally { setPhotoBusy(false); }
  };
  const save = async () => {
    setBusy(true); setErr('');
    try {
      await saveProfile({ name: name.trim(), country, city, bio: bio.trim() });
      toast('Сохранено');
      if (router.canGoBack()) router.back(); else router.replace('/profile');
    } catch (e: any) { setErr(e?.message || 'Не сохранилось'); } finally { setBusy(false); }
  };
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen title="Профиль" footer={<Button title="Сохранить" kind="primary" loading={busy} disabled={name.trim().length < 2} onPress={save} />}>
        <View style={{ alignItems: 'center', gap: 10 }}>
          <Tap onPress={pickPhoto} disabled={photoBusy} scaleTo={0.95} accessibilityLabel="Изменить фото профиля">
            <Avatar name={name || user?.name || '·'} id={user?.id} uri={user?.avatar} size={104} />
            <View style={{ position: 'absolute', right: 0, bottom: 0, width: 34, height: 34, borderRadius: 17, backgroundColor: c.inverse,
              alignItems: 'center', justifyContent: 'center', borderWidth: 3, borderColor: c.bg }}>
              <Icon name="camera" size={16} color={c.onInverse} />
            </View>
          </Tap>
          <Tap onPress={pickPhoto} disabled={photoBusy}><Txt v="subhead" tone="accent" style={{ fontFamily: 'Onest_600SemiBold' }}>{photoBusy ? 'Загружаем…' : user?.avatar ? 'Изменить фото' : 'Добавить фото'}</Txt></Tap>
          {user?.avatar ? <Tap onPress={() => saveAvatar('').then(() => toast('Фото убрано'))}><Txt v="footnote">Убрать фото</Txt></Tap> : null}
        </View>
        <View style={{ gap: 6 }}>
          <Txt v="title1">{user?.name ? 'Профиль' : 'Как вас зовут?'}</Txt>
          <Txt v="callout" tone="muted">Профиль видят все участники приложения: имя, страна и город. Можно только имя, без фамилии.</Txt>
        </View>
        <Field label="Имя" value={name} onChangeText={setName} maxLength={80} placeholder="Анна" autoComplete="given-name" />
        <Field label="Статус" value={bio} onChangeText={setBio} maxLength={160} multiline multilineHeight={80}
          placeholder="Пара слов о себе: чем занимаетесь, что ищете" hint={`${bio.length}/160`} />
        <View style={{ gap: 8 }}>
          <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold', marginLeft: 4 }}>Страна</Txt>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {COUNTRIES.map((c) => <Chip key={c} title={c} on={c === country} onPress={() => pickCountry(c)} />)}
          </View>
        </View>
        <View style={{ gap: 8 }}>
          <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold', marginLeft: 4 }}>Город</Txt>
          <View style={{ flexDirection: 'row' }}>
            <Chip title={city || 'Выбрать город'} icon="location" on={!!city} onPress={() => setPicker(true)} />
          </View>
        </View>
        {err ? <Txt v="callout" tone="danger">{err}</Txt> : null}
      </PageScreen>
      <CitySheet visible={picker} value={city} country={country} onPick={setCity} onClose={() => setPicker(false)} />
      <AvatarCropper uri={pick?.uri ?? null} onDone={upload} onCancel={() => setPick(null)} />
    </KeyboardAvoidingView>
  );
}

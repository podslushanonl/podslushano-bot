import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';
import { saveProfile, useAuth } from '@/api/auth';
import { CitySheet } from '@/features/common/CitySheet';
import { asCountry, CITIES_BY_COUNTRY, COUNTRIES, Country } from '@/lib/countries';
import { Button, Chip, Field, PageScreen, Txt, useToast } from '@/ui';

export default function ProfileEdit() {
  const { user } = useAuth();
  const toast = useToast();
  const [name, setName] = useState(user?.name || '');
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
    setName(user.name || ''); setCountry(asCountry(user.country)); setCity(user.city || '');
  }, [user]);
  const pickCountry = (c: Country) => {
    setCountry(c);
    if (city && !CITIES_BY_COUNTRY[c].includes(city)) setCity('');   // город из другой страны сбрасываем
  };
  const save = async () => {
    setBusy(true); setErr('');
    try {
      await saveProfile({ name: name.trim(), country, city });
      toast('Сохранено');
      if (router.canGoBack()) router.back(); else router.replace('/profile');
    } catch (e: any) { setErr(e?.message || 'Не сохранилось'); } finally { setBusy(false); }
  };
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen title="Профиль" footer={<Button title="Сохранить" kind="primary" loading={busy} disabled={name.trim().length < 2} onPress={save} />}>
        <View style={{ gap: 6 }}>
          <Txt v="title1">{user?.name ? 'Профиль' : 'Как вас зовут?'}</Txt>
          <Txt v="callout" tone="muted">Профиль видят все участники приложения: имя, страна и город. Можно только имя, без фамилии.</Txt>
        </View>
        <Field label="Имя" value={name} onChangeText={setName} maxLength={80} placeholder="Анна" autoComplete="given-name" />
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
    </KeyboardAvoidingView>
  );
}

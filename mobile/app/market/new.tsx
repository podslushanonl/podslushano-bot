import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { MarketIcon } from '@/components/MarketIcon';
import { Button, Eyebrow, H, Loading, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { useAuth } from '@/lib/auth';
import { routeForError } from '@/lib/community';
import { Category, ContactForm, browse, getListing, notifyMarketChanged, photoUrl, shrinkForWeb, submitListing } from '@/lib/market';

const CONTACTS: [keyof ContactForm, string, string, any][] = [
  ['telegram', 'Telegram', '@username', 'default'],
  ['whatsapp', 'WhatsApp', '+31 6 12345678', 'phone-pad'],
  ['phone', 'Телефон', '+31 6 12345678', 'phone-pad'],
  ['email', 'Почта', 'name@mail.com', 'email-address'],
  ['instagram', 'Instagram', '@username', 'default'],
];

function Chip({ title, on, onPress }: { title: string; on: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[s.chip, on && s.chipOn]}>
      <Text style={[s.chipT, on && { color: '#fff' }]}>{title}</Text>
    </Pressable>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={s.label}>{label}</Text>
      {children}
      {hint ? <Text style={s.hint}>{hint}</Text> : null}
    </View>
  );
}

export default function NewListing() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const { user } = useAuth();
  const [cats, setCats] = useState<Category[]>([]);
  const [cities, setCities] = useState<string[]>([]);
  const [ready, setReady] = useState(!id);
  const [category, setCategory] = useState('');
  const [intent, setIntent] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [price, setPrice] = useState('');
  const [city, setCity] = useState(user?.city || '');
  const [nationwide, setNationwide] = useState(false);
  const [contacts, setContacts] = useState<ContactForm>({});
  const [photo, setPhoto] = useState<string | undefined>(undefined); // undefined — не менять, '' — убрать
  const [preview, setPreview] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    browse({ offset: 0 }).then((d) => { setCats(d.categories); setCities(d.cities); }).catch(() => {});
    if (!id) return;
    getListing(Number(id)).then((l) => {
      setCategory(l.cat); setIntent(l.intent); setTitle(l.title); setDescription(l.description || '');
      setPrice(l.price); setCity(l.form?.city || ''); setNationwide(!!l.form?.nationwide);
      setContacts(l.form?.contacts || {}); setPreview(photoUrl(l)); setReady(true);
    }).catch(() => router.back());
  }, [id]);

  const cat = cats.find((c) => c.key === category);
  const pick = async () => {
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7, base64: true });
    if (r.canceled || !r.assets?.[0]) return;
    const a = r.assets[0];
    const data = a.base64 ? `data:image/jpeg;base64,${a.base64}` : await shrinkForWeb(a.uri);
    setPhoto(data); setPreview(a.uri);
  };

  const publish = async () => {
    if (busy) return;
    setBusy(true); setErr('');
    try {
      const d = await submitListing({ id: id ? Number(id) : undefined, category, intent, title: title.trim(),
        description: description.trim(), price: price.trim(), city: city.trim(), nationwide, contacts, photo });
      notifyMarketChanged();
      if (d.pay_url) await WebBrowser.openBrowserAsync(d.pay_url);
      router.replace({ pathname: '/market/[id]', params: { id: String(d.id) } });
    } catch (e: any) { if (!routeForError(e)) setErr(e?.message || 'Не отправилось'); }
    finally { setBusy(false); }
  };

  if (!ready) return <Loading />;
  const input = (value: string, set: (v: string) => void, placeholder: string, extra: object = {}) => (
    <TextInput value={value} onChangeText={set} placeholder={placeholder} placeholderTextColor={C.muted} style={s.input} {...extra} />
  );
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Stack.Screen options={{ title: id ? 'Изменить объявление' : 'Новое объявление' }} />
      <ScrollView contentContainerStyle={{ padding: 20, gap: 18, paddingBottom: 60 }} keyboardShouldPersistTaps="handled">
        <View style={{ gap: 6 }}>
          <Eyebrow>Барахолка</Eyebrow>
          <H size={24}>{id ? 'Изменить объявление' : 'Подать объявление'}</H>
          <P muted>Бесплатно, кроме жилья. После проверки модератором объявление появится в приложении и в Telegram-боте на 30 дней.</P>
        </View>

        <Field label="Категория">
          <View style={s.wrap}>
            {cats.map((c) => <Chip key={c.key} title={c.title} on={category === c.key} onPress={() => { setCategory(c.key); setIntent(''); }} />)}
          </View>
          {category === 'housing' ? <Text style={s.hint}>Размещение жилья платное. Оплата — после заполнения анкеты.</Text> : null}
        </Field>

        {cat?.intents.length ? (
          <Field label="Что именно">
            <View style={s.wrap}>
              {cat.intents.map((i) => <Chip key={i.key} title={i.title} on={intent === i.key} onPress={() => setIntent(i.key)} />)}
            </View>
          </Field>
        ) : null}

        <Field label="Заголовок" hint="Коротко и по делу: «Детская коляска Bugaboo»">
          {input(title, setTitle, 'Что предлагаете или ищете', { maxLength: 100 })}
        </Field>
        <Field label="Описание" hint={`${description.length}/600 · состояние, размеры, когда и где забрать`}>
          {input(description, setDescription, 'Пара предложений о главном', { multiline: true, maxLength: 600, style: [s.input, { minHeight: 120, textAlignVertical: 'top' }] })}
        </Field>
        <Field label="Цена" hint="Например: €50, договорная, даром. Можно не указывать.">
          {input(price, setPrice, '€', { maxLength: 100 })}
        </Field>

        <Field label="Город">
          <View style={s.wrap}>
            <Chip title="Вся страна / онлайн" on={nationwide} onPress={() => setNationwide(!nationwide)} />
            {!nationwide && [...new Set([...(user?.city ? [user.city] : []), ...cities])].map((c) => (
              <Chip key={c} title={c} on={city === c} onPress={() => setCity(c)} />
            ))}
          </View>
          {!nationwide ? input(city, setCity, 'Или напишите свой: Haarlem, Leiden…', { maxLength: 60 }) : null}
        </Field>

        <Field label="Фото" hint="Одно фото. Метаданные и геопозиция удаляются автоматически.">
          {preview && photo !== '' ? (
            <View style={{ gap: 8 }}>
              <Image source={{ uri: preview }} style={s.preview} contentFit="cover" />
              <View style={s.wrap}>
                <Chip title="Другое фото" on={false} onPress={pick} />
                <Chip title="Убрать" on={false} onPress={() => { setPhoto(''); setPreview(''); }} />
              </View>
            </View>
          ) : (
            <Pressable onPress={pick} style={s.addPhoto}>
              <MarketIcon name="photo" color={C.accent} size={26} />
              <Text style={{ color: C.accent, fontWeight: '700' }}>Добавить фото</Text>
            </Pressable>
          )}
        </Field>

        <Field label="Контакты" hint="Хотя бы один. Их увидят все, кто откроет объявление.">
          {CONTACTS.map(([key, label, ph, kb]) => (
            <View key={key} style={s.contactRow}>
              <Text style={s.contactL}>{label}</Text>
              <TextInput value={contacts[key] || ''} onChangeText={(v) => setContacts({ ...contacts, [key]: v })}
                placeholder={ph} placeholderTextColor={C.muted} keyboardType={kb} autoCapitalize="none" autoCorrect={false}
                style={[s.input, { flex: 1 }]} />
            </View>
          ))}
        </Field>

        <Button title={busy ? 'Отправляем…' : id ? 'Сохранить и отправить на проверку' : 'Отправить на проверку'}
          onPress={publish} disabled={busy || !category || !title.trim()} />
        {err ? <Text style={{ color: C.warn, fontSize: 15 }}>{err}</Text> : null}
        <P muted>Подавая объявление, вы соглашаетесь с правилами сообщества. Услуги специалистов размещаются в КонтактGuide.</P>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  label: { fontSize: 15, fontWeight: '700', color: C.ink },
  hint: { fontSize: 13, color: C.muted },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: 999, backgroundColor: C.card, borderWidth: 1, borderColor: C.line },
  chipOn: { backgroundColor: C.ink, borderColor: C.ink },
  chipT: { fontSize: 14, fontWeight: '600', color: C.ink },
  input: { backgroundColor: C.card, borderRadius: 14, borderWidth: 1, borderColor: C.line, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16, color: C.ink },
  preview: { width: '100%', aspectRatio: 4 / 3, borderRadius: 18, backgroundColor: C.line },
  addPhoto: { borderWidth: 1.5, borderStyle: 'dashed', borderColor: C.accent, borderRadius: 18, paddingVertical: 26, alignItems: 'center', gap: 6, backgroundColor: C.accentSoft },
  contactRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  contactL: { width: 86, fontSize: 14, color: C.text, fontWeight: '600' },
});

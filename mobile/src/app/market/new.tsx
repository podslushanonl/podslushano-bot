import * as ImagePicker from 'expo-image-picker';
import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';
import { useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { absUrl, ContactForm, Listing, MAX_PHOTOS, marketChanged, shrinkForWeb, submitListing, useListing, useMarketMeta } from '@/api/market';
import { CitySheet } from '@/features/common/CitySheet';
import { radius, useTheme } from '@/theme';
import { Button, Chip, Field, Icon, IconButton, Img, PageScreen, Skeleton, Tap, Txt, useToast } from '@/ui';

const CONTACTS: [keyof ContactForm, string, string, any][] = [
  ['telegram', 'Telegram', '@username', 'default'],
  ['whatsapp', 'WhatsApp', '+31 6 12345678', 'phone-pad'],
  ['phone', 'Телефон', '+31 6 12345678', 'phone-pad'],
  ['email', 'Почта', 'name@mail.com', 'email-address'],
  ['instagram', 'Instagram', '@username', 'default'],
];

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <View style={{ gap: 10 }}>
      <View style={{ gap: 2 }}>
        <Txt v="headline">{title}</Txt>
        {hint ? <Txt v="footnote">{hint}</Txt> : null}
      </View>
      {children}
    </View>
  );
}

export default function NewListing() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const editId = id ? Number(id) : 0;
  const existing = useListing(editId);
  // Форма для правки появляется, когда объявление загружено: поля сразу заполнены
  if (editId && !existing.data) return <PageScreen title="Объявление"><Skeleton h={40} /><Skeleton h={200} r={24} /></PageScreen>;
  return <ListingForm editId={editId} initial={existing.data} />;
}

function ListingForm({ editId, initial: l }: { editId: number; initial?: Listing }) {
  const { c } = useTheme();
  const toast = useToast();
  const { user } = useAuth();
  const meta = useMarketMeta();
  const [category, setCategory] = useState(l?.cat || '');
  const [intent, setIntent] = useState(l?.intent || '');
  const [title, setTitle] = useState(l?.title || '');
  const [description, setDescription] = useState(l?.description || '');
  const [price, setPrice] = useState(l?.price || '');
  const [city, setCity] = useState(l ? l.form?.city || '' : user?.city || '');
  const [nationwide, setNationwide] = useState(!!l?.form?.nationwide);
  const [contacts, setContacts] = useState<ContactForm>(l?.form?.contacts || {});
  // Фото по порядку: payload — "keep:<номер>" для уже загруженных или картинка для новых; первое — обложка
  const [photos, setPhotos] = useState<{ key: string; preview: string; payload: string }[]>(
    (l?.photos || []).map((u, i) => ({ key: `old${i}`, preview: absUrl(u), payload: `keep:${i}` })));
  const [picker, setPicker] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');


  const cat = meta.data?.categories.find((x) => x.key === category);
  const pick = async () => {
    const left = MAX_PHOTOS - photos.length;
    if (left <= 0) return;
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7, base64: true,
      allowsMultipleSelection: true, selectionLimit: left, orderedSelection: true });
    if (r.canceled || !r.assets?.length) return;
    const added = await Promise.all(r.assets.slice(0, left).map(async (a, i) => ({
      key: `new${Date.now()}${i}`, preview: a.uri,
      payload: a.base64 ? `data:image/jpeg;base64,${a.base64}` : await shrinkForWeb(a.uri),
    })));
    setPhotos((cur) => [...cur, ...added].slice(0, MAX_PHOTOS));
  };
  const remove = (key: string) => setPhotos((cur) => cur.filter((p) => p.key !== key));
  const makeCover = (key: string) => setPhotos((cur) => [...cur.filter((p) => p.key === key), ...cur.filter((p) => p.key !== key)]);

  const publish = async () => {
    if (busy) return;
    setBusy(true); setErr('');
    try {
      const d = await submitListing({ id: editId || undefined, category, intent, title: title.trim(), description: description.trim(),
        price: price.trim(), city: city.trim(), nationwide, contacts, photos: photos.map((p) => p.payload) });
      marketChanged();
      if (d.pay_url) await WebBrowser.openBrowserAsync(d.pay_url);
      toast(d.pay_url ? 'Анкета сохранена' : 'Отправлено на проверку');
      router.replace({ pathname: '/market/[id]', params: { id: String(d.id) } });
    } catch (e: any) { if (!routeForError(e)) setErr(e?.message || 'Не отправилось'); }
    finally { setBusy(false); }
  };

  const ready = category && (!cat?.intents.length || intent) && title.trim().length >= 5 && description.trim().length >= 20 && (nationwide || city.trim())
    && Object.values(contacts).some((v) => (v || '').trim());

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen title={editId ? 'Изменить объявление' : 'Новое объявление'}
        footer={<Button title={editId ? 'Сохранить и отправить на проверку' : 'Отправить на проверку'} kind="primary" loading={busy} disabled={!ready} onPress={publish} />}>
        <View style={{ gap: 6 }}>
          <Txt v="title1">{editId ? 'Изменить объявление' : 'Подать объявление'}</Txt>
          <Txt v="callout" tone="muted">Бесплатно, кроме жилья. После проверки модератором объявление появится в приложении и в Telegram-боте на 30 дней.</Txt>
        </View>

        <Section title="Категория">
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {(meta.data?.categories || []).map((x) => <Chip key={x.key} title={x.title} on={category === x.key} onPress={() => { setCategory(x.key); setIntent(''); }} />)}
          </View>
          {category === 'housing' ? <Txt v="footnote">Размещение жилья платное, оплата — после заполнения анкеты.</Txt> : null}
        </Section>

        {cat?.intents.length ? (
          <Section title="Что именно">
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
              {cat.intents.map((i) => <Chip key={i.key} title={i.title} on={intent === i.key} onPress={() => setIntent(i.key)} />)}
            </View>
          </Section>
        ) : null}

        <Section title="Фото" hint={`До ${MAX_PHOTOS} фото. Первое — обложка; нажмите на фото, чтобы сделать его обложкой. Данные о месте съёмки удаляются.`}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -20 }}
            contentContainerStyle={{ gap: 10, paddingHorizontal: 20 }}>
            {photos.map((p, i) => (
              <Tap key={p.key} onPress={() => makeCover(p.key)} scaleTo={0.96} accessibilityLabel={i ? `Фото ${i + 1}: сделать обложкой` : 'Обложка'}>
                <Img source={p.preview} style={{ width: 120, height: 150, borderRadius: radius.l }} />
                {i === 0 ? (
                  <View style={{ position: 'absolute', left: 8, bottom: 8, backgroundColor: c.hero, borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 4 }}>
                    <Txt v="caption" color={c.onHero} style={{ fontFamily: 'Onest_700Bold' }}>Обложка</Txt>
                  </View>
                ) : null}
                <View style={{ position: 'absolute', top: 6, right: 6 }}>
                  <IconButton icon="close" label="Убрать фото" size={32} onPress={() => remove(p.key)} />
                </View>
              </Tap>
            ))}
            {photos.length < MAX_PHOTOS ? (
              <Tap onPress={pick} scaleTo={0.96} accessibilityLabel="Добавить фото"
                style={{ width: photos.length ? 120 : 260, height: 150, borderRadius: radius.l, borderWidth: 1.5, borderStyle: 'dashed', borderColor: c.lineStrong,
                  alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: c.bgElevated }}>
                <View style={{ width: 46, height: 46, borderRadius: 16, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
                  <Icon name="camera" size={22} color={c.accentText} />
                </View>
                <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>{photos.length ? 'Ещё' : 'Добавить фото'}</Txt>
                {!photos.length ? <Txt v="caption">С фото объявления смотрят чаще</Txt> : null}
              </Tap>
            ) : null}
          </ScrollView>
        </Section>

        <Field label="Заголовок" value={title} onChangeText={setTitle} maxLength={100} placeholder="Например: детская коляска Bugaboo" hint="Коротко и по делу" />
        <Field label="Описание" value={description} onChangeText={setDescription} maxLength={600} multiline placeholder="Состояние, размеры, когда и где забрать"
          hint={`${description.length}/600`} />
        <Field label="Цена" value={price} onChangeText={setPrice} maxLength={100} placeholder="€50, договорная или даром" hint="Можно не указывать" />

        <Section title="Где">
          <View style={{ flexDirection: 'row', gap: 8, flexWrap: 'wrap' }}>
            <Chip title="Вся страна / онлайн" on={nationwide} onPress={() => setNationwide(!nationwide)} />
            {!nationwide ? <Chip title={city || 'Выбрать город'} icon="location" on={!!city} onPress={() => setPicker(true)} /> : null}
          </View>
        </Section>

        <Section title="Контакты" hint="Хотя бы один. Их увидят все, кто откроет объявление.">
          {CONTACTS.map(([key, label, ph, kb]) => (
            <Field key={key} label={label} value={contacts[key] || ''} onChangeText={(v) => setContacts({ ...contacts, [key]: v })}
              placeholder={ph} keyboardType={kb} autoCapitalize="none" autoCorrect={false} />
          ))}
        </Section>

        {err ? <Txt v="callout" tone="danger">{err}</Txt> : null}
        <Txt v="footnote">Подавая объявление, вы соглашаетесь с правилами сообщества. Услуги специалистов размещаются в КонтактGuide.</Txt>
      </PageScreen>
      <CitySheet visible={picker} value={city} onPick={setCity} onClose={() => setPicker(false)} extra={user?.city ? [user.city] : []} />
    </KeyboardAvoidingView>
  );
}

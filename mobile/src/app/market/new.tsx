import * as ImagePicker from 'expo-image-picker';
import { router, useLocalSearchParams } from 'expo-router';
import { ReactNode, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { absUrl, CATEGORIES, Listing, MAX_PHOTOS, marketChanged, shrinkForWeb, submitListing, useListing } from '@/api/market';
import { CitySheet } from '@/features/common/CitySheet';
import { PickSheet } from '@/features/market/PickSheet';
import { useCountry } from '@/lib/useCity';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { BackButton, BAR_H, Button, Field, Icon, IconButton, IconName, Img, Skeleton, Tap, TopBar, Txt, useScrollY, useToast } from '@/ui';

type Photo = { key: string; preview: string; payload: string };
const STEPS = ['Фото', 'Категория и город', 'Описание'];

export default function NewListing() {
  const { id } = useLocalSearchParams<{ id?: string }>();
  const editId = id ? Number(id) : 0;
  const existing = useListing(editId);
  const { c } = useTheme();
  // Форма для правки появляется, когда объявление загружено: поля сразу заполнены
  if (editId && !existing.data) {
    return <View style={{ flex: 1, backgroundColor: c.bg, padding: 20, paddingTop: 120, gap: 14 }}><Skeleton h={40} /><Skeleton h={220} r={20} /></View>;
  }
  return <ListingForm editId={editId} initial={existing.data} />;
}

/** Пункт выбора, как строка системного Picker: подпись слева, значение и стрелка справа. */
function PickRow({ label, value, icon, placeholder, onPress }: { label: string; value?: string; icon?: IconName; placeholder: string; onPress: () => void }) {
  const { c } = useTheme();
  return (
    <View style={{ gap: 7 }}>
      <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold', marginLeft: 4 }}>{label}</Txt>
      <Tap onPress={onPress} scaleTo={0.98} accessibilityLabel={`${label}: ${value || placeholder}`}
        style={{ flexDirection: 'row', alignItems: 'center', gap: 12, minHeight: 56, paddingHorizontal: 14, borderRadius: radius.m,
          backgroundColor: c.bgElevated, borderWidth: HAIRLINE, borderColor: c.line }}>
        {icon ? <Icon name={icon} thin size={22} color={value ? c.accent : c.muted} /> : null}
        <Txt v="body" color={value ? c.ink : c.faint} style={{ flex: 1 }} numberOfLines={1}>{value || placeholder}</Txt>
        <Icon name="down" thin size={16} color={c.muted} />
      </Tap>
    </View>
  );
}

function Step({ n, title, hint, children }: { n: number; title: string; hint?: string; children: ReactNode }) {
  return (
    <View style={{ gap: 16 }}>
      <View style={{ gap: 4 }}>
        <Txt v="overline" tone="accent">Шаг {n} из {STEPS.length}</Txt>
        <Txt v="title1">{title}</Txt>
        {hint ? <Txt v="callout" tone="muted">{hint}</Txt> : null}
      </View>
      {children}
    </View>
  );
}

function ListingForm({ editId, initial: l }: { editId: number; initial?: Listing }) {
  const { c } = useTheme();
  const toast = useToast();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const { user } = useAuth();
  const country = useCountry();
  const { y, onScroll } = useScrollY();
  const [step, setStep] = useState(0);
  const [category, setCategory] = useState(l?.cat || '');
  const [title, setTitle] = useState(l?.title || '');
  const [description, setDescription] = useState(l?.description || '');
  const [price, setPrice] = useState(l?.price_value != null ? String(l.price_value) : '');
  const [city, setCity] = useState(l?.city || user?.city || '');
  // Фото по порядку: payload — "keep:<номер>" для уже загруженных или картинка для новых; первое — обложка
  const [photos, setPhotos] = useState<Photo[]>((l?.photos || []).map((u, i) => ({ key: `old${i}`, preview: absUrl(u), payload: `keep:${i}` })));
  const [sheet, setSheet] = useState<'cat' | 'city' | 'other' | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const cat = CATEGORIES.find((x) => x.key === category);
  const free = category === 'free';
  const side = Math.floor((Math.min(width, 640) - 40 - 16) / 3);

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

  const okStep = [true, !!category && !!city, title.trim().length >= 3 && description.trim().length >= 10];
  const last = step === STEPS.length - 1;

  const publish = async () => {
    if (busy) return;
    setBusy(true); setErr('');
    try {
      const d = await submitListing({ id: editId || undefined, category, title: title.trim(), description: description.trim(),
        price: free ? '0' : price.trim(), city, photos: photos.map((p) => p.payload) });
      marketChanged();
      toast(editId ? 'Изменения сохранены' : 'Объявление опубликовано');
      router.replace({ pathname: '/market/[id]', params: { id: String(d.id) } });
    } catch (e: any) { if (!routeForError(e)) setErr(e?.message || 'Не опубликовалось'); }
    finally { setBusy(false); }
  };
  const next = () => { if (!okStep[step]) return; if (last) publish(); else setStep(step + 1); };

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: c.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView onScroll={onScroll} scrollEventThrottle={16} keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingTop: insets.top + BAR_H + 16, paddingHorizontal: 20, paddingBottom: insets.bottom + 130, gap: 22 }}>
        {/* Прогресс по шагам */}
        <View style={{ flexDirection: 'row', gap: 6 }}>
          {STEPS.map((s, i) => (
            <Tap key={s} onPress={() => { if (i < step || okStep.slice(0, i).every(Boolean)) setStep(i); }} scaleTo={1} style={{ flex: 1, gap: 6 }}
              accessibilityLabel={`Шаг ${i + 1}: ${s}`}>
              <View style={{ height: 4, borderRadius: 2, backgroundColor: i <= step ? c.accent : c.line }} />
              <Txt v="caption" color={i === step ? c.ink : c.faint} numberOfLines={1}
                style={{ fontFamily: i === step ? 'Onest_700Bold' : 'Onest_500Medium' }}>{s}</Txt>
            </Tap>
          ))}
        </View>

        {step === 0 ? (
          <Step n={1} title="Добавьте фото" hint={`До ${MAX_PHOTOS} фото, первое — обложка. Нажмите на фото, чтобы убрать его. Место съёмки из фото удаляется.`}>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
              {Array.from({ length: MAX_PHOTOS }, (_, i) => {
                const p = photos[i];
                if (p) {
                  return (
                    <Tap key={p.key} onPress={() => remove(p.key)} scaleTo={0.95} accessibilityLabel={`Убрать фото ${i + 1}`}
                      style={{ width: side, height: side, borderRadius: radius.m, overflow: 'hidden' }}>
                      <Img source={p.preview} style={{ width: side, height: side }} />
                      <View style={{ position: 'absolute', top: 6, right: 6, width: 26, height: 26, borderRadius: 13, backgroundColor: 'rgba(0,0,0,0.6)',
                        alignItems: 'center', justifyContent: 'center' }}>
                        <Icon name="close" size={13} color="#FFFFFF" />
                      </View>
                      {i === 0 ? (
                        <View style={{ position: 'absolute', left: 6, bottom: 6, backgroundColor: 'rgba(0,0,0,0.6)', borderRadius: radius.pill, paddingHorizontal: 8, paddingVertical: 3 }}>
                          <Txt v="caption" color="#FFFFFF" style={{ fontFamily: 'Onest_700Bold' }}>Обложка</Txt>
                        </View>
                      ) : null}
                    </Tap>
                  );
                }
                const add = i === photos.length;
                return (
                  <Tap key={`slot${i}`} onPress={pick} disabled={!add} scaleTo={0.95} accessibilityLabel="Добавить фото"
                    style={{ width: side, height: side, borderRadius: radius.m, alignItems: 'center', justifyContent: 'center', gap: 6,
                      backgroundColor: add ? c.bgElevated : c.bgSunken, borderWidth: add ? 1 : HAIRLINE, borderColor: add ? c.lineStrong : c.line }}>
                    <Icon name={add ? 'plus' : 'photo'} thin size={add ? 26 : 22} color={add ? c.accent : c.faint} />
                    {add ? <Txt v="caption" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>{photos.length ? 'Ещё' : 'Добавить'}</Txt> : null}
                  </Tap>
                );
              })}
            </View>
            <Txt v="footnote" tone="muted">Объявления с фото смотрят в разы чаще. Можно пропустить этот шаг.</Txt>
          </Step>
        ) : step === 1 ? (
          <Step n={2} title="Категория и город" hint="Так покупатели найдут объявление в нужном разделе.">
            <PickRow label="Категория" value={cat?.title} icon={cat?.icon || 'apps'} placeholder="Выберите категорию" onPress={() => setSheet('cat')} />
            {cat ? <Txt v="footnote" tone="muted" style={{ marginTop: -8, marginLeft: 4 }}>{cat.hint}</Txt> : null}
            <PickRow label="Город" value={city} icon="location" placeholder="Выберите город" onPress={() => setSheet('city')} />
          </Step>
        ) : (
          <Step n={3} title="Расскажите о товаре" hint={cat ? `${cat.title} · ${city}` : undefined}>
            <Field label="Название" value={title} onChangeText={setTitle} maxLength={100} placeholder="Например: велосипед Gazelle, 28”" />
            {free ? (
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, padding: 14, borderRadius: radius.m, backgroundColor: c.accentSoft }}>
                <Icon name="gift" thin size={20} color={c.accent} />
                <Txt v="callout" tone="ink" style={{ flex: 1 }}>Раздел «Даром»: цена — бесплатно, покупатель забирает сам.</Txt>
              </View>
            ) : (
              <Field label="Цена (€)" value={price} onChangeText={(v) => setPrice(v.replace(/[^\d]/g, '').slice(0, 7))} keyboardType="number-pad" inputMode="numeric"
                placeholder="0" hint="Пусто — договорная, 0 — бесплатно"
                left={<Txt v="title3" color={price ? c.ink : c.faint}>€</Txt>} />
            )}
            <Field label="Описание товара" value={description} onChangeText={setDescription} maxLength={2000} multiline multilineHeight={150}
              placeholder="Состояние, размер, комплект, где и когда можно забрать" hint={`${description.length}/2000`} />
            {err ? <Txt v="callout" tone="danger">{err}</Txt> : null}
            <Txt v="footnote" tone="muted">Объявление публикуется сразу на 30 дней. Покупатели напишут вам в личные сообщения приложения.</Txt>
          </Step>
        )}
      </ScrollView>

      <TopBar y={y} always title={editId ? 'Изменить объявление' : 'Новое объявление'} left={<BackButton />} />

      <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, flexDirection: 'row', gap: 10, paddingHorizontal: 16,
        paddingTop: 12, paddingBottom: insets.bottom + 12, backgroundColor: c.bg, borderTopWidth: HAIRLINE, borderTopColor: c.line }}>
        {step > 0 ? <IconButton icon="back" kind="plain" label="Назад" onPress={() => setStep(step - 1)} size={54} /> : null}
        <View style={{ flex: 1 }}>
          <Button title={last ? (editId ? 'Сохранить' : 'Опубликовать') : step === 0 && !photos.length ? 'Пропустить' : 'Далее'}
            kind="accent" loading={busy} disabled={!okStep[step]} onPress={next} />
        </View>
      </View>

      <PickSheet visible={sheet === 'cat'} title="Категория" value={category} onClose={() => setSheet(null)} onPick={setCategory}
        options={CATEGORIES.map((x) => ({ key: x.key, title: x.title, hint: x.hint, icon: x.icon }))} />
      {/* Город объявления — любой населённый пункт; профиль при этом не меняется */}
      <CitySheet visible={sheet === 'city'} value={city} country={country} mine={false} extra={[user?.city || '']} onPick={setCity} onClose={() => setSheet(null)} />
    </KeyboardAvoidingView>
  );
}

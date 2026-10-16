import { useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { Place, saveLocation, searchPlaces } from '@/api/geo';
import { Country } from '@/lib/countries';
import { locateMe } from '@/lib/location';
import { radius, type as T, useTheme } from '@/theme';
import { Glass, Icon, IconName, Tap, Txt, useToast } from '@/ui';

function Line({ icon, title, sub, on, onPress, accent, busy }: {
  icon: IconName; title: string; sub?: string; on?: boolean; onPress: () => void; accent?: boolean; busy?: boolean;
}) {
  const { c } = useTheme();
  return (
    <Tap scaleTo={0.99} onPress={onPress} disabled={busy} accessibilityLabel={title}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 18, paddingVertical: 12, borderTopWidth: 1, borderTopColor: c.line }}>
      <View style={{ width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center', backgroundColor: accent ? c.accent : c.bgSunken }}>
        {busy ? <ActivityIndicator color={accent ? c.onAccent : c.ink} /> : <Icon name={icon} size={17} color={accent ? c.onAccent : c.ink} />}
      </View>
      <View style={{ flex: 1 }}>
        <Txt v="bodyStrong" color={accent ? c.accentText : undefined}>{title}</Txt>
        {sub ? <Txt v="footnote" tone="muted">{sub}</Txt> : null}
      </View>
      {on ? <Icon name="check" size={18} color={c.accentText} /> : null}
    </Tap>
  );
}

/** Выбор населённого пункта: любой город, пригород или деревня Нидерландов, Германии и Бельгии.
 *  mine — это «мой город»: тогда есть «Определить по GPS», а выбор из поиска сохраняет и координаты места
 *  (лента «Рядом» — в радиусе 50 км). Без mine (фильтр барахолки, место поста) — только название. */
export function CitySheet({ visible, value, onPick, onClose, extra = [], allLabel, country, mine }: {
  visible: boolean; value: string; onPick: (c: string) => void; onClose: () => void; extra?: string[];
  /** Искать только в этой стране (фильтры); без неё — во всех трёх. */
  country?: Country;
  /** Строка «все города» первой в списке (выбор — пустая строка). */
  allLabel?: string;
  mine?: boolean;
}) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { user } = useAuth();
  const [text, setText] = useState('');
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState('');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const own = mine ?? !allLabel;
  const results = useQuery({
    queryKey: ['geo', q, allLabel ? country || '' : ''], enabled: visible && q.length >= 2, staleTime: 3600_000,
    queryFn: () => searchPlaces(q, allLabel ? country : undefined),
  });
  const type = (t: string) => {
    setText(t);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setQ(t.trim()), 300);
  };
  const done = (city: string) => { setText(''); setQ(''); onPick(city); onClose(); };
  const pick = async (p: Place) => {
    // «Мой город» у вошедшего — сохраняем вместе с координатами места: «Рядом» сразу считает радиус от него
    if (own && user && p.lat != null && p.lng != null) {
      setBusy(p.name);
      try { await saveLocation(p.lat, p.lng); } catch (e: any) { toast(e?.message || 'Не сохранилось', 'error'); setBusy(''); return; }
      setBusy('');
    }
    done(p.name);
  };
  const gps = async () => {
    setBusy('gps');
    try {
      const p = await locateMe();
      toast(`Вы в ${p.name}`);
      done(p.name);
    } catch (e: any) { toast(e?.message || 'Не получилось определить место', 'error'); } finally { setBusy(''); }
  };
  const fixed = [...new Set([value, ...extra].filter(Boolean))];
  const found = (results.data || []).filter((p) => !fixed.includes(p.name));
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <Pressable onPress={onClose} accessibilityLabel="Закрыть" style={{ flex: 1, backgroundColor: c.scrim, justifyContent: 'flex-end', padding: 10, paddingBottom: insets.bottom + 10 }}>
          <Pressable onPress={() => {}}>
            <Glass radius={radius.xl} strong style={{ maxHeight: 560 }}>
              <Txt v="headline" center style={{ paddingTop: 18, paddingBottom: 12 }}>{allLabel ? 'Город' : 'Ваш город или деревня'}</Txt>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 14, marginBottom: 12, paddingHorizontal: 12, height: 46,
                borderRadius: radius.m, backgroundColor: c.bgSunken }}>
                <Icon name="search" size={17} color={c.muted} />
                <TextInput value={text} onChangeText={type} placeholder="Любой город или деревня" placeholderTextColor={c.faint}
                  autoCorrect={false} accessibilityLabel="Поиск населённого пункта" returnKeyType="search"
                  style={[T.body, { flex: 1, color: c.ink, outlineStyle: 'none' } as any]} />
                {results.isFetching ? <ActivityIndicator color={c.muted} /> : null}
              </View>
              <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: 8 }}>
                {own && user ? <Line icon="location" title="Определить по GPS" sub="Точно, даже маленькую деревню" accent busy={busy === 'gps'} onPress={gps} /> : null}
                {allLabel ? <Line icon="globe" title={allLabel} on={!value} onPress={() => done('')} /> : null}
                {fixed.map((city) => <Line key={city} icon="location" title={city} on={city === value} onPress={() => done(city)} />)}
                {found.map((p) => (
                  <Line key={p.name + p.country} icon="location" title={p.name} sub={p.country} busy={busy === p.name} onPress={() => pick(p)} />
                ))}
                {q.length >= 2 && !results.isFetching && !found.length && !fixed.some((x) => x.toLowerCase().startsWith(q.toLowerCase())) ? (
                  <Txt v="callout" tone="muted" center style={{ padding: 18 }}>
                    {results.isError ? 'Поиск недоступен. Попробуйте позже.' : 'Ничего не нашлось в Нидерландах, Германии и Бельгии'}
                  </Txt>
                ) : null}
              </ScrollView>
            </Glass>
          </Pressable>
        </Pressable>
      </KeyboardAvoidingView>
    </Modal>
  );
}

import * as Location from 'expo-location';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, TextInput, View } from 'react-native';
import { Town, townAt, useTownSearch } from '@/api/towns';
import { setHome, setProvince, useProvince } from '@/lib/province';
import { PROVINCES, provinceById, ProvinceId } from '@/lib/provinces';
import { HAIRLINE, radius, type as T, useTheme } from '@/theme';
import { Button, Group, Icon, PageScreen, Row, Txt, useToast } from '@/ui';

/**
 * Где человек живёт: город или деревня (поиск по справочнику PDOK или геолокация), а по нему — провинция.
 * По месту жительства выбираются станция NS, события и места рядом с домом.
 * first=1 — первый запуск: после выбора открываются разделы.
 */
export default function HomePicker() {
  const { c } = useTheme();
  const { first } = useLocalSearchParams<{ first?: string }>();
  const { province, home } = useProvince();
  const toast = useToast();
  const [q, setQ] = useState('');
  const [locating, setLocating] = useState(false);
  const [found, setFound] = useState<Town | null>(null);
  const search = useTownSearch(q);

  const done = () => { if (first) router.replace('/'); else router.back(); };
  const chooseTown = (t: Town) => { setHome({ name: t.name, gemeente: t.gemeente, lat: t.lat, lon: t.lon }, t.province); done(); };
  const chooseProvince = (id: ProvinceId) => { setProvince(id); done(); };

  const locate = async () => {
    setLocating(true);
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (!perm.granted) { toast('Доступ к геолокации не дан. Найдите город через поиск.'); return; }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const t = await townAt(pos.coords.latitude, pos.coords.longitude);
      if (t) setFound(t); else toast('Похоже, вы сейчас не в Нидерландах. Найдите город через поиск.');
    } catch {
      toast('Не получилось определить место. Найдите город через поиск.');
    } finally {
      setLocating(false);
    }
  };

  const townRow = (t: Town, i: number, accent = false) => (
    <Row key={`${t.name}-${t.gemeente}-${i}`} first={i === 0} title={t.name} icon="location" iconBg={accent ? c.accent : undefined}
      sub={[t.gemeente && t.gemeente !== t.name ? `gemeente ${t.gemeente}` : '', provinceById(t.province)?.name].filter(Boolean).join(' · ')}
      onPress={() => chooseTown(t)} />
  );
  const typing = q.trim().length >= 2;

  return (
    <PageScreen title="Место жительства">
      <View style={{ gap: 8 }}>
        <Txt v="title1" accessibilityRole="header">Где вы живёте?</Txt>
        <Txt v="callout" tone="muted">
          Укажите город или деревню: покажем вашу станцию, события и места рядом с домом, а афишу и контакт-гайд — по вашей провинции.
        </Txt>
      </View>

      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, height: 50, borderRadius: radius.l,
        backgroundColor: c.bgElevated, borderWidth: HAIRLINE, borderColor: c.line }}>
        <Icon name="search" size={18} color={c.muted} />
        <TextInput value={q} onChangeText={setQ} placeholder="Город или деревня, например Oss" placeholderTextColor={c.faint}
          autoCorrect={false} autoCapitalize="words" returnKeyType="search" accessibilityLabel="Город или деревня"
          style={[T.callout, { flex: 1, color: c.ink, outlineStyle: 'none' } as any]} />
        {search.isFetching ? <ActivityIndicator color={c.muted} /> : null}
      </View>

      {typing ? (
        search.data?.length ? <Group title="Найдено">{search.data.map((t, i) => townRow(t, i))}</Group>
          : search.isError ? <Txt v="callout" tone="muted">Поиск не сработал. Проверьте интернет или выберите провинцию ниже.</Txt>
            : !search.isFetching ? <Txt v="callout" tone="muted">Ничего не нашли. Проверьте написание: названия латиницей, например Den Bosch или Zwolle.</Txt>
              : null
      ) : found ? (
        <Group title="По геолокации">{townRow(found, 0, true)}</Group>
      ) : (
        <Button kind="secondary" icon="location" title="Определить по геолокации" loading={locating} onPress={locate} />
      )}

      {home && !typing ? (
        <Group title="Сейчас выбрано">
          <Row first title={home.name} sub={province?.name} icon="home" chevron={false}
            right={<Icon name="check" size={18} color={c.accentText} />} />
        </Group>
      ) : null}

      {!typing ? (
        <Group title="Или только провинция">
          {PROVINCES.map((p, i) => (
            <Row key={p.id} first={i === 0} title={p.name} sub={p.short} onPress={() => chooseProvince(p.id)} chevron={false}
              right={!home && province?.id === p.id ? <Icon name="check" size={18} color={c.accentText} /> : null} />
          ))}
        </Group>
      ) : null}
    </PageScreen>
  );
}

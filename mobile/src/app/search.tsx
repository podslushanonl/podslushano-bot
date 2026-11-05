import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { useSpecialists } from '@/api/guide';
import { useHandbook } from '@/api/handbook';
import { kindOf, placesOf } from '@/api/places';
import { EventCard } from '@/features/afisha/EventCard';
import { SpecialistCard } from '@/features/guide/SpecialistCard';
import { PlaceCard } from '@/features/places/PlaceCard';
import { useProvinceEvents } from '@/features/province/data';
import { useProvince } from '@/lib/province';
import { useTheme } from '@/theme';
import { Empty, Field, Group, Icon, PageScreen, Row, Txt } from '@/ui';

/** Без регистра, диакритики и разницы между е и ё: «Keukenhof» найдётся и по «keukenhof», «ёлка» — по «елка». */
const norm = (s: string) => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ё/g, 'е');
const LIMIT = 5;

/** Поиск по выбранной провинции: события, места, специалисты; справки — по всей стране. */
export default function Search() {
  const { c } = useTheme();
  const { province } = useProvince();
  const p = province!;
  const [text, setText] = useState('');
  const ev = useProvinceEvents(p.id);
  const sp = useSpecialists();
  const hb = useHandbook();
  const q = norm(text.trim());
  const words = q.split(/\s+/).filter(Boolean);
  const hit = (...fields: (string | undefined)[]) => {
    const hay = norm(fields.filter(Boolean).join(' '));
    return words.every((w) => hay.includes(w));
  };

  const res = useMemo(() => {
    if (q.length < 2) return null;
    return {
      events: ev.events.filter((e) => hit(e.h, e.s, e.venue, e.city, e.cat)),
      places: placesOf(p.id).filter((x) => hit(x.name, x.ru, x.town, x.desc, ...x.kinds.map((k) => kindOf(k).title))),
      people: (sp.data || []).filter((s) => (s.province === p.name || (s.online && !s.province)) && hit(s.name, s.category, s.description, s.city)),
      // совпадение в заголовке справки важнее, чем в кратком описании
      guides: (hb.data || []).filter((g) => hit(g.title, g.lead)).sort((a, b) => Number(hit(b.title)) - Number(hit(a.title))),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, ev.events, sp.data, hb.data, p.id]);
  const total = res ? res.events.length + res.places.length + res.people.length + res.guides.length : 0;

  return (
    <PageScreen title="Поиск">
      <Field autoFocus placeholder={`Поиск: ${p.name}`} value={text} onChangeText={setText} returnKeyType="search"
        left={<Icon name="search" size={18} color={c.faint} />} accessibilityLabel="Поиск по провинции" clearButtonMode="while-editing" />
      {!res ? (
        <Txt v="callout" tone="muted">События, места и специалисты провинции {p.name}, а также справки по всей стране. Например: «музей», «стоматолог», «DigiD».</Txt>
      ) : !total ? (
        <Empty icon="search" title="Ничего не нашли" text="Попробуйте другое слово или проверьте написание." />
      ) : (
        <>
          {res.events.length ? (
            <View style={{ gap: 10 }}>
              <Txt v="title2" accessibilityRole="header">События</Txt>
              {res.events.slice(0, LIMIT).map((e) => <EventCard key={e.key} e={e} />)}
            </View>
          ) : null}
          {res.places.length ? (
            <View style={{ gap: 10 }}>
              <Txt v="title2" accessibilityRole="header">Места</Txt>
              {res.places.slice(0, LIMIT).map((x) => <PlaceCard key={x.id} p={x} />)}
            </View>
          ) : null}
          {res.people.length ? (
            <View style={{ gap: 10 }}>
              <Txt v="title2" accessibilityRole="header">Специалисты</Txt>
              {res.people.slice(0, LIMIT).map((s) => <SpecialistCard key={s.id} s={s} />)}
            </View>
          ) : null}
          {res.guides.length ? (
            <Group title="Справочник">
              {res.guides.slice(0, LIMIT).map((g, i) => (
                <Row key={g.id} first={i === 0} icon="doc" title={g.title}
                  onPress={() => router.push({ pathname: '/handbook/[id]', params: { id: String(g.id) } })} />
              ))}
            </Group>
          ) : null}
          {[res.events, res.places, res.people, res.guides].some((l) => l.length > LIMIT)
            ? <Txt v="footnote">Показаны первые совпадения. Уточните запрос, чтобы найти точнее.</Txt> : null}
        </>
      )}
    </PageScreen>
  );
}

import { router } from 'expo-router';
import { useMemo } from 'react';
import { ScrollView, View } from 'react-native';
import { useContent, useDisruptions, useWeather, weatherIcon, weatherText } from '@/api/content';
import { newsProvince, useNlDates } from '@/api/daily';
import { NewsRow } from '@/features/news/NewsRow';
import { DateCard } from '@/features/daily/DateCard';
import { JobCard } from '@/features/daily/JobCard';
import { kindOf, placesOf } from '@/api/places';
import { EventCard } from '@/features/afisha/EventCard';
import { useProvinceEvents } from '@/features/province/data';
import { HeaderActions, ProvinceSwitch } from '@/features/province/ProvinceSwitch';
import { plural } from '@/lib/format';
import { km, useProvince } from '@/lib/province';
import { useMyStation } from '@/lib/station';
import { radius, useTheme } from '@/theme';
import { Button, Card, Empty, Group, Icon, Img, Row, Skeleton, TabScreen, Tap, Txt } from '@/ui';

const dateLine = () => new Date().toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/Amsterdam' });

/** Блок с заголовком и ссылкой «Все» справа. */
function Section({ title, more, onMore, children }: { title: string; more?: string; onMore?: () => void; children: React.ReactNode }) {
  return (
    <View style={{ gap: 12 }}>
      <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <Txt v="title2" accessibilityRole="header">{title}</Txt>
        {more && onMore ? <Tap onPress={onMore} hitSlop={10}><Txt v="subhead" tone="accent">{more}</Txt></Tap> : null}
      </View>
      {children}
    </View>
  );
}

/** «Сегодня»: погода, ближайшие события, поезда и коротко о провинции. */
export default function Today() {
  const { c } = useTheme();
  const { province, home } = useProvince();
  const p = province!;
  // Погода, станция и места — у дома, если человек указал город; иначе по столице провинции
  const w = useWeather(home?.name || p.capital, home ? [home.lat, home.lon] : [p.lat, p.lon]);
  const ev = useProvinceEvents(p.id);
  const content = useContent();
  const dates = useNlDates(p.id);
  // Новости: сначала своей провинции, всего четыре
  const news = useMemo(() => {
    const all = (content.data?.news || []).map((n) => ({ n, local: newsProvince(n.h) === p.id }));
    return [...all.filter((x) => x.local), ...all.filter((x) => !x.local)].slice(0, 4);
  }, [content.data, p.id]);
  const soon = (dates.data || []).slice(0, 2);
  const jobs = (content.data?.jobs || []).slice(0, 2);
  const dis = useDisruptions();
  const my = useMyStation();
  const mineNow = (dis.data?.now || []).filter((d) => (d.stations || []).includes(my.st[0])).length;
  const allNow = dis.data?.now?.length || 0;
  // События в своём городе (или gemeente) — первыми
  const events = useMemo(() => {
    if (!home) return ev.events;
    const local = (e: { city?: string }) => [home.name, home.gemeente].some((n) => n && sameTown(e.city, n));
    return [...ev.events.filter(local), ...ev.events.filter((e) => !local(e))];
  }, [ev.events, home]);
  // «Куда сходить»: у дома — ближайшие места с фото, иначе самые известные места провинции
  const picks = useMemo(() => {
    const list = placesOf(p.id).filter((x) => x.img);
    if (!home) return list.slice(0, 10);
    return list.map((x) => ({ x, d: km(home.lat, home.lon, x.lat, x.lon) })).sort((a, b) => a.d - b.d).slice(0, 10).map((r) => r.x);
  }, [p.id, home]);

  return (
    <TabScreen title="Сегодня" sub={dateLine()} above={<ProvinceSwitch />} right={<HeaderActions />}
      refreshing={ev.isRefetching} onRefresh={() => Promise.all([ev.refetch(), w.refetch(), dis.refetch(), dates.refetch()])}>
      {/* Погода в провинции */}
      <Card pad={18} style={{ borderRadius: radius.l, flexDirection: 'row', alignItems: 'center', gap: 16 }}>
        {w.data ? (
          <>
            <View style={{ width: 56, height: 56, borderRadius: radius.m, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
              <Icon name={weatherIcon(w.data.code)} size={28} color={c.accentText} />
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <Txt v="title1">{w.data.temp}°</Txt>
              <Txt v="subhead" tone="muted">
                {weatherText(w.data.code)}, ветер {w.data.wind} км/ч{w.data.rainSoon ? `, дождь около ${w.data.rainSoon}` : ''}
              </Txt>
              <Txt v="footnote" tone="faint">{home?.name || p.capital}</Txt>
            </View>
          </>
        ) : <Skeleton h={56} />}
      </Card>

      {soon.length ? (
        <Section title="Скоро" more="Все даты" onMore={() => router.push('/dates')}>
          {soon.map((d) => <DateCard key={d.date + d.title} d={d} short />)}
        </Section>
      ) : null}

      {news.length ? (
        <Section title="Новости" more="Все новости" onMore={() => router.push('/news')}>
          <Card pad={16} style={{ borderRadius: radius.l, gap: 14 }}>
            {news.map(({ n, local }, i) => (
              <View key={n.id} style={{ gap: 14 }}>
                {i ? <View style={{ height: 1, backgroundColor: c.line }} /> : null}
                <NewsRow n={n} local={local} />
              </View>
            ))}
          </Card>
        </Section>
      ) : null}

      <Section title="Ближайшие события" more="Вся афиша" onMore={() => router.push('/afisha')}>
        {ev.isLoading ? <View style={{ gap: 12 }}>{[0, 1].map((i) => <Skeleton key={i} h={122} r={radius.xl} />)}</View>
          : ev.isError && !events.length ? <Card style={{ borderRadius: radius.l }}><Empty icon="warning" title="События не загрузились" text="Проверьте интернет и попробуйте ещё раз." action={<Button kind="secondary" title="Повторить" onPress={() => ev.refetch()} />} /></Card>
          : events.length ? events.slice(0, 3).map((e) => <EventCard key={e.key} e={e} />)
            : <Card style={{ borderRadius: radius.l }}><Empty icon="ticket" title={`В ${p.name} пока нет событий`} text="Афиша пополняется каждую неделю." /></Card>}
      </Section>

      {picks.length ? (
        <Section title={home ? 'Рядом с домом' : 'Куда сходить'} more="Все места" onMore={() => router.push('/places')}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -20 }}
            contentContainerStyle={{ paddingHorizontal: 20, gap: 12 }}>
            {picks.map((x) => (
              <Tap key={x.id} onPress={() => router.push({ pathname: '/place/[id]', params: { id: x.id } })} scaleTo={0.97}
                accessibilityLabel={`${kindOf(x.kinds[0]).one}: ${x.name}`}
                style={{ width: 200, backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: 1, borderColor: c.line, overflow: 'hidden' }}>
                <Img source={x.img} style={{ width: '100%', height: 130, backgroundColor: c.placeholder }} />
                <View style={{ padding: 12, gap: 3 }}>
                  <Txt v="overline" tone="accent" numberOfLines={1}>{kindOf(x.kinds[0]).one}</Txt>
                  <Txt v="headline" numberOfLines={2} style={{ minHeight: 44 }}>{x.name}</Txt>
                  {x.town ? <Txt v="footnote" numberOfLines={1}>{x.town}</Txt> : null}
                </View>
              </Tap>
            ))}
          </ScrollView>
        </Section>
      ) : null}

      <Group title="В дороге">
        <Row first icon="train" iconBg={mineNow ? c.danger : c.success} title={my.st[1]}
          sub={mineNow ? `${mineNow} ${plural(mineNow, ['сбой', 'сбоя', 'сбоев'])} на вашей станции`
            : allNow ? `На вашей станции сбоев нет · по стране ${allNow}` : 'Сбоев сейчас нет'} onPress={() => router.push('/trains')} />
      </Group>

      {jobs.length ? (
        <Section title="Работа" more="Все вакансии" onMore={() => router.push('/jobs')}>
          {jobs.map((j) => <JobCard key={j.id} j={j} compact />)}
        </Section>
      ) : null}

      <Section title={p.name}>
        <Card pad={18} style={{ borderRadius: radius.l, gap: 10 }}>
          <Txt v="body">{p.short}</Txt>
          <Txt v="subhead" tone="muted">Столица провинции: {p.capital}</Txt>
          <Button kind="secondary" size="s" full={false} icon="pin" title="Места провинции" onPress={() => router.push('/places')} />
        </Card>
      </Section>
    </TabScreen>
  );
}

/** Один ли это населённый пункт: «'s-Hertogenbosch» и «s-Hertogenbosch», регистр и диакритика не важны. */
function sameTown(a: string | undefined, b: string) {
  const n = (s: string) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/^['’]s-/, '').replace(/[^a-z]/g, '');
  return !!a && n(a) === n(b);
}

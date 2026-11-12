import { router } from 'expo-router';
import { useMemo } from 'react';
import { ScrollView, View } from 'react-native';
import { newsProvince, useNlDates } from '@/api/daily';
import { useContent, useDepartures, useWeather, weatherIcon, weatherText } from '@/api/content';
import { DateCard } from '@/features/daily/DateCard';
import { NewsRow } from '@/features/news/NewsRow';
import { HeaderActions, ProvinceSwitch } from '@/features/province/ProvinceSwitch';
import { dayMonth, weekday } from '@/lib/format';
import { useProvince } from '@/lib/province';
import { useMyStation } from '@/lib/station';
import { MOCK_SAVE } from '@/mocks';
import { HAIRLINE, radius, space, useTheme } from '@/theme';
import { Button, Card, Icon, Img, Skeleton, TabScreen, Tap, Txt } from '@/ui';

const dateLine = () => new Date().toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/Amsterdam' });
const isoPlus = (days: number) => new Date(Date.now() + days * 86400000).toLocaleDateString('sv-SE', { timeZone: 'Europe/Amsterdam' });

/** Блок с заголовком и ссылкой «Все» справа. */
function Section({ title, more, onMore, children }: { title: string; more?: string; onMore?: () => void; children: React.ReactNode }) {
  const { c } = useTheme();
  return (
    <View style={{ gap: space.gap }}>
      <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <Txt v="title2" accessibilityRole="header">{title}</Txt>
        {more && onMore ? <Tap onPress={onMore} hitSlop={14} haptic="light"><Txt v="subhead" color={c.secondary} style={{ fontWeight: '600' }}>{more}</Txt></Tap> : null}
      </View>
      {children}
    </View>
  );
}

/** «Лента»: Нидерланды сейчас, главное за неделю, новости и «Сэкономить». */
export default function Feed() {
  const { c } = useTheme();
  const { province: p, chosen, home } = useProvince();
  const w = useWeather(home?.name || p.capital, home ? [home.lat, home.lon] : [p.lat, p.lon]);
  const my = useMyStation();
  const dep = useDepartures(my.st[0]);
  const content = useContent();
  const dates = useNlDates(p.id);
  const today = isoPlus(0);
  const week = isoPlus(7);
  // «Главное за неделю»: события ближайших семи дней с постером; свои (по провинции) — первыми
  const top = useMemo(() => {
    const list = (content.data?.events || []).filter((e) => e.img && (e.end || e.date) >= today && e.date <= week);
    return [...list.filter((e) => e.province === p.id), ...list.filter((e) => e.province !== p.id)].slice(0, 10);
  }, [content.data, today, week, p.id]);
  const news = useMemo(() => {
    const all = (content.data?.news || []).map((n) => ({ n, local: newsProvince(n.h) === p.id }));
    return [...all.filter((x) => x.local), ...all.filter((x) => !x.local)].slice(0, 6);
  }, [content.data, p.id]);
  const trains = (dep.data || []).filter((d) => !d.cancelled).slice(0, 3);
  const soon = (dates.data || []).slice(0, 1);

  return (
    <TabScreen title="Лента" sub={dateLine()} above={<ProvinceSwitch />} right={<HeaderActions />}
      refreshing={content.isRefetching} onRefresh={() => Promise.all([content.refetch(), w.refetch(), dep.refetch(), dates.refetch()])}>

      {/* Нидерланды сейчас: погода и ближайшие поезда со своей станции */}
      <Card pad={16} style={{ gap: 14 }}>
        <Txt v="overline" tone="muted">Нидерланды сейчас · {home?.name || p.capital}</Txt>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 14 }}>
          {w.data ? (
            <>
              <View style={{ width: 52, height: 52, borderRadius: radius.control, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
                <Icon name={weatherIcon(w.data.code)} size={28} color={c.accentText} />
              </View>
              <View style={{ flex: 1 }}>
                <Txt v="title1">{w.data.temp}°</Txt>
                <Txt v="subhead" tone="muted" numberOfLines={2}>
                  {weatherText(w.data.code)}, ветер {w.data.wind} км/ч{w.data.rainSoon ? `, дождь около ${w.data.rainSoon}` : ''}
                </Txt>
              </View>
            </>
          ) : <Skeleton h={52} r={radius.control} />}
        </View>
        <View style={{ height: HAIRLINE, backgroundColor: c.line }} />
        <Tap onPress={() => router.push('/trains')} haptic="light" scaleTo={0.99} accessibilityLabel={`Поезда со станции ${my.st[1]}. Открыть расписание`}
          style={{ gap: 8 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Icon name="train" size={18} color={c.secondary} />
            <Txt v="headline" style={{ flex: 1 }} numberOfLines={1}>{my.st[1]}</Txt>
            <Txt v="subhead" color={c.secondary} style={{ fontWeight: '600' }}>Расписание</Txt>
          </View>
          {dep.isLoading ? <Skeleton h={18} w="70%" />
            : trains.length ? trains.map((d, i) => (
              <View key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
                <Txt v="subhead" tone="ink" style={{ width: 44, fontVariant: ['tabular-nums'], fontWeight: '700' }}>{d.time}</Txt>
                <Txt v="subhead" tone="muted" numberOfLines={1} style={{ flex: 1 }}>{d.direction}</Txt>
                {d.delay ? <Txt v="caption" tone="danger" style={{ fontWeight: '700' }}>+{d.delay}</Txt> : null}
                <Txt v="caption" tone="muted">путь {d.track || '—'}</Txt>
              </View>
            )) : <Txt v="subhead" tone="muted">Ближайших отправлений нет</Txt>}
        </Tap>
        {!chosen ? (
          <Button kind="secondary" size="s" icon="home" title="Указать свой город и станцию" onPress={() => router.push('/province')} />
        ) : null}
      </Card>

      {soon.map((d) => (
        <Tap key={d.date + d.title} onPress={() => router.push('/dates')} scaleTo={0.99} accessibilityLabel={`Скоро: ${d.title}. Все важные даты`}>
          <DateCard d={d} short />
        </Tap>
      ))}

      <Section title="Главное за неделю" more="Все события" onMore={() => router.push('/events')}>
        {content.isLoading ? <Skeleton h={210} r={radius.card} /> : top.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -space.screen }}
            contentContainerStyle={{ paddingHorizontal: space.screen, gap: space.gap }}>
            {top.map((e) => (
              <Tap key={e.key} onPress={() => router.push({ pathname: '/event/[key]', params: { key: e.key } })} scaleTo={0.97}
                accessibilityLabel={`${e.h}, ${weekday(e.date)}, ${dayMonth(e.date)}`}
                style={{ width: 264, backgroundColor: c.bgElevated, borderRadius: radius.card, borderWidth: HAIRLINE, borderColor: c.line, overflow: 'hidden' }}>
                <Img source={e.img} style={{ width: '100%', aspectRatio: 16 / 9 }} accessibilityIgnoresInvertColors />
                <View style={{ padding: 12, gap: 3 }}>
                  <Txt v="overline" tone="accent">{weekday(e.date)}, {dayMonth(e.date)}{e.time ? ` · ${e.time}` : ''}</Txt>
                  <Txt v="headline" numberOfLines={2} style={{ minHeight: 44 }}>{e.h}</Txt>
                  {e.city ? <Txt v="footnote" color={c.secondary} numberOfLines={1}>{e.city}</Txt> : null}
                </View>
              </Tap>
            ))}
          </ScrollView>
        ) : <Card><Txt v="callout" tone="muted">На этой неделе событий с афишей пока нет. Загляните во вкладку «События».</Txt></Card>}
      </Section>

      <Section title="Новости" more="Все новости" onMore={() => router.push('/news')}>
        {content.isLoading ? <View style={{ gap: space.gap }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={64} r={radius.control} />)}</View> : (
          <Card pad={16} style={{ gap: 14 }}>
            {news.map(({ n, local }, i) => (
              <View key={n.id} style={{ gap: 14 }}>
                {i ? <View style={{ height: HAIRLINE, backgroundColor: c.line }} /> : null}
                <NewsRow n={n} local={local} />
              </View>
            ))}
          </Card>
        )}
      </Section>

      <Section title="Сэкономить" more="Все статьи" onMore={() => router.push('/save')}>
        {MOCK_SAVE.slice(0, 3).map((a) => (
          <Tap key={a.id} onPress={() => router.push('/save')} scaleTo={0.99} accessibilityLabel={a.title}
            style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, backgroundColor: c.bgElevated, borderRadius: radius.card,
              borderWidth: HAIRLINE, borderColor: c.line }}>
            <View style={{ width: 44, height: 44, borderRadius: radius.control, backgroundColor: c.secondarySoft, alignItems: 'center', justifyContent: 'center' }}>
              <Icon name="tag" size={20} color={c.secondary} />
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <Txt v="overline" color={c.secondary}>{a.tag} · {a.mins} мин</Txt>
              <Txt v="headline" numberOfLines={2}>{a.title}</Txt>
            </View>
          </Tap>
        ))}
      </Section>
    </TabScreen>
  );
}

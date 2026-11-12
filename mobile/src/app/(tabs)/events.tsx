import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { useWalks, walkUrl } from '@/api/allo';
import { EventItem, useContent } from '@/api/content';
import { EventCard } from '@/features/afisha/EventCard';
import { HeaderActions } from '@/features/province/ProvinceSwitch';
import { dayMonth, monthTitle, weekday } from '@/lib/format';
import { openUrl } from '@/lib/open';
import { MOCK_MEETINGS } from '@/mocks';
import { HAIRLINE, radius, space, useTheme } from '@/theme';
import { Button, ChipRow, EmptyState, Icon, Img, Segmented, Skeleton, TabScreen, Tap, Txt } from '@/ui';

const PAGE = 30;
type Part = 'afisha' | 'meet';
// Крупные города — всегда в этом порядке, остальные добавляются по числу событий
const TOP = ['Amsterdam', 'Rotterdam', 'Den Haag', 'Utrecht', 'Eindhoven'];
const todayIso = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Amsterdam' });

/** «События»: афиша всей страны с фильтром по городу и встречи сообщества (allo.walks). */
export default function Events() {
  const [part, setPart] = useState<Part>('afisha');
  const [city, setCity] = useState('');
  const q = useContent();
  const walks = useWalks();
  const today = todayIso();

  const upcoming = useMemo(() => (q.data?.events || [])
    .filter((e) => (e.end || e.date) >= today)
    .sort((a, b) => (a.date + (a.time || '')).localeCompare(b.date + (b.time || ''))), [q.data, today]);
  const cities = useMemo(() => {
    const n = new Map<string, number>();
    upcoming.forEach((e) => { if (e.city) n.set(e.city, (n.get(e.city) || 0) + 1); });
    const rest = [...n.entries()].filter(([k]) => !TOP.includes(k)).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([k]) => k);
    return [...TOP, ...rest];
  }, [upcoming]);
  const shown = useMemo(() => upcoming.filter((e) => !city || e.city === city), [upcoming, city]);
  const [page, setPage] = useState({ key: '', n: PAGE });
  const limit = page.key === city ? page.n : PAGE;
  const groups = useMemo(() => {
    const m = new Map<string, EventItem[]>();
    shown.slice(0, limit).forEach((e) => { const k = (e.date < today ? today : e.date).slice(0, 7); m.set(k, [...(m.get(k) || []), e]); });
    return [...m.entries()];
  }, [shown, limit, today]);

  return (
    <TabScreen title="События" right={<HeaderActions />} refreshing={q.isRefetching || walks.isRefetching}
      onRefresh={() => Promise.all([q.refetch(), walks.refetch()])}>
      <Segmented items={[{ key: 'afisha', title: 'Афиша' }, { key: 'meet', title: 'Встречи' }]} value={part} onChange={setPart} />

      {part === 'afisha' ? (
        <>
          <ChipRow items={[{ key: '', title: 'Все' }, ...cities.map((x) => ({ key: x, title: x }))]} value={city} onChange={setCity} />
          {q.isLoading ? <View style={{ gap: space.gap }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={122} r={radius.card} />)}</View>
            : q.isError && !shown.length ? (
              <EmptyState icon="warning" title="Афиша не загрузилась" text="Проверьте интернет и попробуйте ещё раз."
                action={<Button kind="secondary" title="Повторить" onPress={() => q.refetch()} />} />
            ) : !shown.length ? (
              <EmptyState icon="ticket" title={city ? `В ${city} пока нет событий` : 'Событий пока нет'}
                text="Знаете о событии? Добавьте его в афишу: его увидят все, кто ищет, куда сходить."
                action={<Button kind="accent" icon="plus" title="Добавить событие" onPress={() => router.push({ pathname: '/create/[kind]', params: { kind: 'event' } })} />} />
            ) : (
              <>
                {groups.map(([month, list]) => (
                  <View key={month} style={{ gap: space.gap }}>
                    <Txt v="title2" accessibilityRole="header">{monthTitle(`${month}-01`)}</Txt>
                    {list.map((e) => <EventCard key={e.key} e={e} />)}
                  </View>
                ))}
                {shown.length > limit ? (
                  <Button kind="secondary" title={`Показать ещё · ${shown.length - limit}`} onPress={() => setPage({ key: city, n: limit + PAGE })} />
                ) : null}
              </>
            )}
        </>
      ) : <Meetings />}
    </TabScreen>
  );
}

/** Встречи сообщества: прогулки allo.walks с сервера; пока их нет — тестовые карточки (этап 2). */
function Meetings() {
  const { c } = useTheme();
  const walks = useWalks();
  if (walks.isLoading) return <View style={{ gap: space.gap }}>{[0, 1].map((i) => <Skeleton key={i} h={220} r={radius.card} />)}</View>;
  const real = walks.data || [];
  return (
    <>
      <Txt v="callout" tone="muted">Прогулки и встречи русскоязычного сообщества от allo.walks. Бронирование и оплата — через iDEAL.</Txt>
      {real.length ? real.map((w) => {
        const day = w.starts_at.slice(0, 10);
        const left = w.inventory?.available ?? w.capacity;
        return (
          <Tap key={w.key} onPress={() => openUrl(walkUrl())} scaleTo={0.98} accessibilityLabel={`Встреча: ${w.title}`}
            style={{ backgroundColor: c.bgElevated, borderRadius: radius.card, borderWidth: HAIRLINE, borderColor: c.line, overflow: 'hidden' }}>
            <Img source={w.photos[0]?.url} style={{ width: '100%', aspectRatio: 16 / 9 }} accessibilityIgnoresInvertColors />
            <MeetBody title={w.title} place={w.place} when={`${weekday(day)}, ${dayMonth(day)}, ${w.starts_at.slice(11, 16)}`}
              price={`€${(w.price_cents / 100).toFixed(2).replace('.', ',')}`} left={left} />
          </Tap>
        );
      }) : MOCK_MEETINGS.map((m) => (
        <View key={m.key} style={{ backgroundColor: c.bgElevated, borderRadius: radius.card, borderWidth: HAIRLINE, borderColor: c.line, overflow: 'hidden' }}>
          <View style={{ width: '100%', aspectRatio: 16 / 9, backgroundColor: c.secondarySoft, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="people" size={40} color={c.secondary} />
          </View>
          <MeetBody title={m.title} place={m.place} when={m.when} price={m.price} left={m.left} demo />
        </View>
      ))}
    </>
  );
}

function MeetBody({ title, place, when, price, left, demo }: { title: string; place: string; when: string; price: string; left: number; demo?: boolean }) {
  const { c } = useTheme();
  return (
    <View style={{ padding: 14, gap: 4 }}>
      <Txt v="overline" color={c.secondary}>{when}</Txt>
      <Txt v="title3">{title}</Txt>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <View style={{ paddingHorizontal: 10, height: 24, borderRadius: radius.pill, backgroundColor: c.secondarySoft, justifyContent: 'center' }}>
          <Txt v="caption" color={c.secondary} style={{ fontWeight: '600' }}>{place}</Txt>
        </View>
        <Txt v="subhead" tone="muted">{price} · {left ? `осталось мест: ${left}` : 'мест нет'}</Txt>
        {demo ? <Txt v="caption" tone="faint">пример</Txt> : null}
      </View>
    </View>
  );
}

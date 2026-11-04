import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { EventItem } from '@/api/content';
import { EventCard } from '@/features/feed/cards';
import { useProvinceEvents } from '@/features/province/data';
import { HeaderActions, ProvinceSwitch } from '@/features/province/ProvinceSwitch';
import { monthTitle } from '@/lib/format';
import { useProvince } from '@/lib/province';
import { radius } from '@/theme';
import { Button, ChipRow, Empty, Skeleton, TabScreen, Txt } from '@/ui';

type When = 'all' | 'today' | 'weekend' | 'month';
const WHEN: { key: When; title: string }[] = [
  { key: 'all', title: 'Все даты' }, { key: 'today', title: 'Сегодня' }, { key: 'weekend', title: 'Выходные' }, { key: 'month', title: 'Этот месяц' },
];

const iso = (d: Date) => d.toLocaleDateString('sv-SE', { timeZone: 'Europe/Amsterdam' });

/** Попадает ли событие (с учётом многодневных) в выбранный период. */
function inPeriod(e: EventItem, when: When, today: string) {
  if (when === 'all') return true;
  const start = e.date; const end = e.end || e.date;
  let from = today; let to = today;
  if (when === 'weekend') {
    const d = new Date(`${today}T12:00:00`); const wd = d.getDay();
    const sat = new Date(d); sat.setDate(d.getDate() + (wd === 0 ? -1 : 6 - wd));
    const sun = new Date(sat); sun.setDate(sat.getDate() + 1);
    from = wd === 0 ? today : iso(sat); to = iso(sun);
    if (wd === 6) from = today;
  } else if (when === 'month') {
    to = `${today.slice(0, 7)}-31`;
  }
  return start <= to && end >= from;
}

/** Афиша выбранной провинции: фильтр по дате и городу, события по месяцам. */
export default function Afisha() {
  const { province } = useProvince();
  const p = province!;
  const q = useProvinceEvents(p.id);
  const [when, setWhen] = useState<When>('all');
  const [city, setCity] = useState('');
  const cities = useMemo(() => [...new Set(q.events.map((e) => e.city).filter(Boolean) as string[])].sort(), [q.events]);
  const shown = q.events.filter((e) => inPeriod(e, when, q.today) && (!city || e.city === city));
  const groups = useMemo(() => {
    const m = new Map<string, EventItem[]>();
    shown.forEach((e) => { const k = (e.date < q.today ? q.today : e.date).slice(0, 7); m.set(k, [...(m.get(k) || []), e]); });
    return [...m.entries()];
  }, [shown, q.today]);

  return (
    <TabScreen title="Афиша" above={<ProvinceSwitch />} right={<HeaderActions />} refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      <View style={{ gap: 10, marginHorizontal: -20 }}>
        <ChipRow items={WHEN} value={when} onChange={setWhen} />
        {cities.length > 1 ? <ChipRow items={[{ key: '', title: 'Все города' }, ...cities.map((x) => ({ key: x, title: x }))]} value={city} onChange={setCity} /> : null}
      </View>
      {q.isLoading ? <View style={{ gap: 12 }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={122} r={radius.xl} />)}</View>
        : groups.length ? groups.map(([month, list]) => (
          <View key={month} style={{ gap: 12 }}>
            <Txt v="title2" accessibilityRole="header">{monthTitle(`${month}-01`)}</Txt>
            {list.map((e) => <EventCard key={e.key} e={e} />)}
          </View>
        )) : (
          <Empty icon="ticket" title={when === 'all' && !city ? `В ${p.name} пока нет событий` : 'На эти даты событий нет'}
            text={when === 'all' && !city ? 'Афиша пополняется каждую неделю. Можно посмотреть соседнюю провинцию.' : 'Попробуйте другие даты или город.'}
            action={when === 'all' && !city ? <Button kind="secondary" icon="location" title="Сменить провинцию" onPress={() => router.push('/province')} />
              : <Button kind="secondary" title="Показать все даты" onPress={() => { setWhen('all'); setCity(''); }} />} />
        )}
    </TabScreen>
  );
}

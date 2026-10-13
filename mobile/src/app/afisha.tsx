import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { useContent } from '@/api/content';
import { EventCard } from '@/features/feed/cards';
import { monthTitle } from '@/lib/format';
import { ChipRow, Empty, PageScreen, Skeleton, Txt } from '@/ui';

export default function Afisha() {
  const q = useContent();
  const [city, setCity] = useState('');
  const today = new Date().toISOString().slice(0, 10);
  const events = useMemo(() => (q.data?.events || []).filter((e) => (e.end || e.date) >= today), [q.data, today]);
  const cities = useMemo(() => [...new Set(events.map((e) => e.city).filter(Boolean) as string[])].sort(), [events]);
  const shown = events.filter((e) => !city || e.city === city);
  const groups = useMemo(() => {
    const m = new Map<string, typeof shown>();
    shown.forEach((e) => { const k = e.date.slice(0, 7); m.set(k, [...(m.get(k) || []), e]); });
    return [...m.entries()];
  }, [shown]);

  return (
    <PageScreen title="Афиша" refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      <View style={{ gap: 6 }}>
        <Txt v="title1">Афиша</Txt>
        <Txt v="callout" tone="muted">Концерты, спектакли и встречи на русском по всей стране.</Txt>
      </View>
      {cities.length > 1 ? <ChipRow items={[{ key: '', title: 'Все города' }, ...cities.map((x) => ({ key: x, title: x }))]} value={city} onChange={setCity} /> : null}
      {q.isLoading ? <View style={{ gap: 12 }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={122} r={28} />)}</View>
        : groups.length ? groups.map(([month, list]) => (
          <View key={month} style={{ gap: 12 }}>
            <Txt v="title2">{monthTitle(`${month}-01`)}</Txt>
            {list.map((e) => <EventCard key={e.key} e={e} />)}
          </View>
        )) : <Empty icon="ticket" title="Событий пока нет" text={city ? 'Попробуйте другой город.' : 'Загляните позже — афиша обновляется каждую неделю.'} />}
    </PageScreen>
  );
}

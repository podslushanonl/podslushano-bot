import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { ScrollView, View } from 'react-native';
import { useWalks, walkUrl } from '@/api/allo';
import { EventItem } from '@/api/content';
import { EventCard } from '@/features/afisha/EventCard';
import { useProvinceEvents } from '@/features/province/data';
import { HeaderActions, ProvinceSwitch } from '@/features/province/ProvinceSwitch';
import { dayMonth, monthTitle, weekday } from '@/lib/format';
import { openUrl } from '@/lib/open';
import { provinceOfCity } from '@/lib/provinces';
import { useProvince } from '@/lib/province';
import { radius, useTheme } from '@/theme';
import { Button, ChipRow, Empty, Img, Skeleton, TabScreen, Tap, Txt } from '@/ui';

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
  const { c } = useTheme();
  const { province } = useProvince();
  const walksQ = useWalks();
  const p = province!;
  const q = useProvinceEvents(p.id);
  const [when, setWhen] = useState<When>('all');
  const [city, setCity] = useState('');
  // Наши прогулки allo.walks в этой провинции
  const walks = (walksQ.data || []).filter((w) => provinceOfCity(w.place) === p.id);
  const cities = useMemo(() => [...new Set(q.events.map((e) => e.city).filter(Boolean) as string[])].sort(), [q.events]);
  const shown = q.events.filter((e) => inPeriod(e, when, q.today) && (!city || e.city === city));
  const groups = useMemo(() => {
    const m = new Map<string, EventItem[]>();
    shown.forEach((e) => { const k = (e.date < q.today ? q.today : e.date).slice(0, 7); m.set(k, [...(m.get(k) || []), e]); });
    return [...m.entries()];
  }, [shown, q.today]);

  return (
    <TabScreen title="Афиша" above={<ProvinceSwitch />} right={<HeaderActions />} refreshing={q.isRefetching} onRefresh={() => Promise.all([q.refetch(), walksQ.refetch()])}>
      <View style={{ gap: 10, marginHorizontal: -20 }}>
        <ChipRow items={WHEN} value={when} onChange={setWhen} />
        {cities.length > 1 ? <ChipRow items={[{ key: '', title: 'Все города' }, ...cities.map((x) => ({ key: x, title: x }))]} value={city} onChange={setCity} /> : null}
      </View>
      {walks.length ? (
        <View style={{ gap: 12 }}>
          <Txt v="title2" accessibilityRole="header">От podslushano.nl</Txt>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -20 }} contentContainerStyle={{ paddingHorizontal: 20, gap: 12 }}>
            {walks.map((w) => {
              const left = w.inventory?.available ?? w.capacity;
              const day = w.starts_at.slice(0, 10);
              return (
                <Tap key={w.key} onPress={() => openUrl(walkUrl())} scaleTo={0.97} accessibilityLabel={`Прогулка allo.walks: ${w.title}`}
                  style={{ width: 240, backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: 1, borderColor: c.line, overflow: 'hidden' }}>
                  <Img source={w.photos[0]?.url} style={{ width: '100%', height: 140, backgroundColor: c.placeholder }} />
                  <View style={{ padding: 12, gap: 3 }}>
                    <Txt v="overline" tone="accent">allo.walks · {weekday(day)}, {dayMonth(day)}, {w.starts_at.slice(11, 16)}</Txt>
                    <Txt v="headline" numberOfLines={2} style={{ minHeight: 44 }}>{w.title}</Txt>
                    <Txt v="footnote">{w.place} · {w.duration}</Txt>
                    <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>
                      {`€${(w.price_cents / 100).toFixed(2).replace('.', ',')} · ${left ? `мест: ${left}` : 'мест нет'}`}
                    </Txt>
                  </View>
                </Tap>
              );
            })}
          </ScrollView>
        </View>
      ) : null}
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

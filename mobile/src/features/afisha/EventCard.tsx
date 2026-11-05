import { router } from 'expo-router';
import { View } from 'react-native';
import { EventItem } from '@/api/content';
import { dayMonth, weekday } from '@/lib/format';
import { radius, useTheme } from '@/theme';
import { Icon, Img, Tap, Txt } from '@/ui';

/** Время для списков («14:05» сегодня, иначе «3 нояб., 14:05»), по Амстердаму. */
export function timeLabel(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  const hm = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Amsterdam' });
  if (d.toDateString() === now.toDateString()) return hm;
  return `${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', timeZone: 'Europe/Amsterdam' })}, ${hm}`;
}

/** Карточка события в афише: постер, дата, название, место, цена. */
export function EventCard({ e }: { e: EventItem }) {
  const { c } = useTheme();
  return (
    <Tap onPress={() => router.push({ pathname: '/event/[key]', params: { key: e.key } })} scaleTo={0.985}
      style={{ flexDirection: 'row', gap: 14, alignItems: 'center', backgroundColor: c.bgElevated, borderRadius: radius.xl, padding: 12, borderWidth: 1, borderColor: c.line }}>
      {e.img ? <Img source={e.img} style={{ width: 78, height: 98, borderRadius: 16 }} />
        : <View style={{ width: 78, height: 98, borderRadius: 16, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}><Icon name="ticket" color={c.accentText} /></View>}
      <View style={{ flex: 1, gap: 4 }}>
        <Txt v="overline" tone="accent">{weekday(e.date)}, {dayMonth(e.date)}{e.time ? ` · ${e.time}` : ''}</Txt>
        <Txt v="headline" numberOfLines={2}>{e.h}</Txt>
        <Txt v="footnote" numberOfLines={1}>{[e.venue, e.city].filter(Boolean).join(', ')}</Txt>
        {e.price ? <Txt v="footnote" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>{e.price}</Txt> : null}
      </View>
    </Tap>
  );
}

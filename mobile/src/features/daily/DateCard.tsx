import { View } from 'react-native';
import { NlDate } from '@/api/daily';
import { dayMonth, weekday } from '@/lib/format';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Icon, IconName, Txt } from '@/ui';

const KIND: Record<NlDate['kind'], { icon: IconName; label: string }> = {
  holiday: { icon: 'calendar', label: 'Выходной' }, day: { icon: 'calendar', label: 'Памятный день' },
  clock: { icon: 'clock', label: 'Время' }, deadline: { icon: 'warning', label: 'Срок' }, school: { icon: 'school', label: 'Школа' },
};

/** Карточка даты: когда, что это и что значит для человека (short — без пояснения). */
export function DateCard({ d, short }: { d: NlDate; short?: boolean }) {
  const { c } = useTheme();
  const k = KIND[d.kind] || KIND.day;
  const range = d.end && d.end !== d.date ? `${dayMonth(d.date)} — ${dayMonth(d.end)}` : `${weekday(d.date)}, ${dayMonth(d.date)}`;
  const warn = d.kind === 'deadline';
  return (
    <View style={{ flexDirection: 'row', gap: 14, backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: HAIRLINE,
      borderColor: warn ? c.accent : c.line, padding: 14 }}>
      <View style={{ width: 40, height: 40, borderRadius: radius.m, backgroundColor: warn ? c.accent : c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name={k.icon} size={20} color={warn ? c.onAccent : c.accentText} />
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <Txt v="overline" tone="accent">{range}</Txt>
        <Txt v="headline">{d.title}{d.nl && d.nl !== d.title ? <Txt v="subhead" tone="muted">{`  ${d.nl}`}</Txt> : null}</Txt>
        {d.text && !short ? <Txt v="subhead" tone="muted">{d.text}</Txt> : null}
      </View>
    </View>
  );
}

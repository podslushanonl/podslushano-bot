import { ScrollView, View } from 'react-native';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Icon, IconName } from './Icon';
import { Tap } from './Tap';
import { Txt } from './Text';

export function Chip({ title, on, onPress, icon }: { title: string; on?: boolean; onPress?: () => void; icon?: IconName }) {
  const { c } = useTheme();
  return (
    <Tap onPress={onPress} scaleTo={0.94} accessibilityState={{ selected: !!on }}
      style={{ height: 38, paddingHorizontal: 15, borderRadius: radius.pill, flexDirection: 'row', alignItems: 'center', gap: 6,
        backgroundColor: on ? c.accentSoft : c.bgElevated, borderWidth: on ? 1 : HAIRLINE, borderColor: on ? c.accent : c.line }}>
      {icon ? <Icon name={icon} size={15} color={on ? c.accentText : c.ink} /> : null}
      <Txt v="subhead" color={on ? c.accentText : c.ink} style={{ fontFamily: 'Onest_600SemiBold' }}>{title}</Txt>
    </Tap>
  );
}

/** Горизонтальная лента чипов с отступами по краям экрана. */
export function ChipRow<T extends string>({ items, value, onChange, pad = 20 }: {
  items: { key: T; title: string; icon?: IconName }[]; value: T; onChange: (k: T) => void; pad?: number;
}) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, paddingHorizontal: pad }}
      style={{ marginHorizontal: -pad, flexGrow: 0 }}>
      {items.map((i) => <Chip key={i.key} title={i.title} icon={i.icon} on={value === i.key} onPress={() => onChange(i.key)} />)}
    </ScrollView>
  );
}

export function Segmented<T extends string>({ items, value, onChange }: { items: { key: T; title: string }[]; value: T; onChange: (k: T) => void }) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: 'row', backgroundColor: c.segTrack, borderRadius: 14, padding: 4, gap: 4 }}>
      {items.map((i) => {
        const on = i.key === value;
        return (
          <Tap key={i.key} onPress={() => onChange(i.key)} scaleTo={0.97} accessibilityRole="tab" accessibilityState={{ selected: on }}
            style={{ flex: 1, height: 38, borderRadius: 11, alignItems: 'center', justifyContent: 'center',
              backgroundColor: on ? c.segOn : 'transparent', shadowColor: '#000', shadowOpacity: on ? 0.08 : 0, shadowRadius: 4, shadowOffset: { width: 0, height: 1 } }}>
            <Txt v="subhead" tone={on ? 'ink' : 'muted'} style={{ fontFamily: on ? 'Onest_700Bold' : 'Onest_600SemiBold' }}>{i.title}</Txt>
          </Tap>
        );
      })}
    </View>
  );
}

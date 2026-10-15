import { ActivityIndicator, StyleProp, View, ViewStyle } from 'react-native';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Glass } from './Glass';
import { Icon, IconName } from './Icon';
import { Tap } from './Tap';
import { Txt } from './Text';

type Kind = 'primary' | 'accent' | 'secondary' | 'glass' | 'danger' | 'plain';

export function Button({ title, onPress, kind = 'primary', icon, size = 'm', loading, disabled, style, full = true }: {
  title: string; onPress: () => void; kind?: Kind; icon?: IconName; size?: 'm' | 's'; loading?: boolean; disabled?: boolean;
  style?: StyleProp<ViewStyle>; full?: boolean;
}) {
  const { c } = useTheme();
  const h = size === 'm' ? 54 : 40;
  const bg = { primary: c.inverse, accent: c.accent, secondary: c.bgElevated, glass: 'transparent', danger: c.bgElevated, plain: 'transparent' }[kind];
  const fg = { primary: c.onInverse, accent: c.onAccent, secondary: c.ink, glass: c.ink, danger: c.danger, plain: c.accentText }[kind];
  const inner = (
    <View style={{ height: h, paddingHorizontal: size === 'm' ? 22 : 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
      {loading ? <ActivityIndicator color={fg} /> : (
        <>
          {icon ? <Icon name={icon} size={size === 'm' ? 19 : 16} color={fg} /> : null}
          <Txt v={size === 'm' ? 'bodyStrong' : 'subhead'} color={fg} style={{ fontFamily: 'Onest_700Bold' }} numberOfLines={1}>{title}</Txt>
        </>
      )}
    </View>
  );
  return (
    <Tap onPress={onPress} disabled={disabled || loading} haptic={kind === 'primary' || kind === 'accent' ? 'light' : 'select'}
      accessibilityLabel={title}
      style={[{ borderRadius: radius.pill, alignSelf: full ? 'stretch' : 'flex-start' }, style]}>
      {kind === 'glass' ? <Glass radius={radius.pill} interactive>{inner}</Glass> : (
        <View style={{ borderRadius: radius.pill, backgroundColor: bg, overflow: 'hidden',
          borderWidth: kind === 'secondary' || kind === 'danger' || kind === 'primary' ? HAIRLINE : 0,
          borderColor: kind === 'primary' ? c.lineStrong : c.line }}>{inner}</View>
      )}
    </Tap>
  );
}

/** Круглая кнопка-иконка. По умолчанию — на стекле (для панелей поверх контента). */
export function IconButton({ icon, onPress, label, kind = 'glass', size = 44, badge, color }: {
  icon: IconName; onPress: () => void; label: string; kind?: 'glass' | 'solid' | 'accent' | 'plain'; size?: number; badge?: boolean; color?: string;
}) {
  const { c } = useTheme();
  const fg = color ?? (kind === 'accent' ? c.onAccent : kind === 'solid' ? c.onInverse : c.ink);
  const body = (
    <View style={{ width: size, height: size, alignItems: 'center', justifyContent: 'center' }}>
      <Icon name={icon} size={size * 0.45} color={fg} />
      {badge ? <View style={{ position: 'absolute', top: size * 0.2, right: size * 0.22, width: 9, height: 9, borderRadius: 5, backgroundColor: c.accent, borderWidth: 2, borderColor: c.bgElevated }} /> : null}
    </View>
  );
  return (
    <Tap onPress={onPress} accessibilityLabel={label} scaleTo={0.9} style={{ borderRadius: size / 2 }}>
      {kind === 'glass' ? <Glass radius={size / 2} interactive>{body}</Glass>
        : <View style={{ borderRadius: size / 2, backgroundColor: kind === 'accent' ? c.accent : kind === 'solid' ? c.inverse : 'transparent' }}>{body}</View>}
    </Tap>
  );
}

import { Image, ImageProps } from 'expo-image';
import { ReactNode, useEffect } from 'react';
import { StyleProp, View, ViewStyle } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withRepeat, withTiming } from 'react-native-reanimated';
import { radius, useTheme } from '@/theme';
import { Icon, IconName } from './Icon';
import { Tap } from './Tap';
import { Txt } from './Text';

/** Карточка на «бумаге» приложения. С onPress — нажимается. */
export function Card({ children, style, onPress, pad = 16 }: { children: ReactNode; style?: StyleProp<ViewStyle>; onPress?: () => void; pad?: number }) {
  const { c } = useTheme();
  const box: ViewStyle = { backgroundColor: c.bgElevated, borderRadius: radius.xl, padding: pad, gap: 10, borderWidth: 1, borderColor: c.line };
  if (!onPress) return <View style={[box, style]}>{children}</View>;
  return <Tap onPress={onPress} scaleTo={0.985} style={[box, style]}>{children}</Tap>;
}

/** Картинка с плавным появлением и нейтральной подложкой, пока грузится. */
export function Img({ style, ...p }: ImageProps) {
  const { c } = useTheme();
  return <Image transition={180} contentFit="cover" {...p} style={[{ backgroundColor: c.placeholder }, style]} />;
}

const AV = [['#FFE3D6', '#8A2E0A'], ['#DDE7F7', '#1E3A8A'], ['#E3F1E7', '#14532D'], ['#F5E6F0', '#831843'], ['#EDE7FB', '#4C1D95'], ['#FDF2D6', '#78350F']];

export function Avatar({ name, size = 44, id = 0 }: { name: string; size?: number; id?: number }) {
  const [bg, fg] = AV[Math.abs(id || name.length) % AV.length];
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, backgroundColor: bg, alignItems: 'center', justifyContent: 'center' }}>
      <Txt v="headline" color={fg} style={{ fontSize: size * 0.4, lineHeight: size * 0.5 }}>{(name || '·').trim().slice(0, 1).toUpperCase()}</Txt>
    </View>
  );
}

export function Badge({ n }: { n: number }) {
  const { c } = useTheme();
  if (!n) return null;
  return (
    <View style={{ minWidth: 20, height: 20, paddingHorizontal: 6, borderRadius: 10, backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center' }}>
      <Txt v="caption" color={c.onAccent} style={{ fontFamily: 'Onest_700Bold' }}>{n > 99 ? '99+' : n}</Txt>
    </View>
  );
}

/** Сгруппированный список строк (как в «Настройках» iOS). */
export function Group({ children, title, style }: { children: ReactNode; title?: string; style?: StyleProp<ViewStyle> }) {
  const { c } = useTheme();
  return (
    <View style={[{ gap: 8 }, style]}>
      {title ? <Txt v="overline" style={{ marginLeft: 6 }}>{title}</Txt> : null}
      <View style={{ backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: 1, borderColor: c.line, overflow: 'hidden' }}>{children}</View>
    </View>
  );
}

export function Row({ title, sub, icon, iconBg, right, onPress, first, danger, chevron = true }: {
  title: string; sub?: string; icon?: IconName; iconBg?: string; right?: ReactNode; onPress?: () => void; first?: boolean; danger?: boolean; chevron?: boolean;
}) {
  const { c } = useTheme();
  const body = (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 13, minHeight: 56,
      borderTopWidth: first ? 0 : 1, borderTopColor: c.line }}>
      {icon ? (
        <View style={{ width: 34, height: 34, borderRadius: 10, backgroundColor: iconBg || c.bgSunken, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name={icon} size={18} color={iconBg ? '#FFFFFF' : c.ink} />
        </View>
      ) : null}
      <View style={{ flex: 1, gap: 2 }}>
        <Txt v="bodyStrong" color={danger ? c.danger : undefined}>{title}</Txt>
        {sub ? <Txt v="footnote">{sub}</Txt> : null}
      </View>
      {right}
      {onPress && chevron ? <Icon name="chevron" size={14} color={c.faint} /> : null}
    </View>
  );
  return onPress ? <Tap onPress={onPress} scaleTo={0.99}>{body}</Tap> : body;
}

/** Заглушка-«скелет» во время загрузки, мягко пульсирует. */
export function Skeleton({ w = '100%', h = 16, r = 10, style }: { w?: number | `${number}%`; h?: number; r?: number; style?: StyleProp<ViewStyle> }) {
  const { c } = useTheme();
  const o = useSharedValue(0.55);
  useEffect(() => { o.set(withRepeat(withTiming(1, { duration: 750 }), -1, true)); }, [o]);
  const a = useAnimatedStyle(() => ({ opacity: o.get() }));
  return <Animated.View style={[{ width: w, height: h, borderRadius: r, backgroundColor: c.placeholder }, a, style]} />;
}

export function Empty({ icon = 'sparkles', title, text, action }: { icon?: IconName; title: string; text?: string; action?: ReactNode }) {
  const { c } = useTheme();
  return (
    <View style={{ alignItems: 'center', gap: 10, paddingVertical: 48, paddingHorizontal: 28 }}>
      <View style={{ width: 64, height: 64, borderRadius: 22, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name={icon} size={28} color={c.accentText} />
      </View>
      <Txt v="title3" center>{title}</Txt>
      {text ? <Txt v="callout" tone="muted" center>{text}</Txt> : null}
      {action ? <View style={{ marginTop: 6, alignSelf: 'stretch' }}>{action}</View> : null}
    </View>
  );
}

import { Text as RNText, TextProps } from 'react-native';
import { type as T, TypeVariant, useTheme } from '@/theme';

type Tone = 'ink' | 'text' | 'muted' | 'faint' | 'accent' | 'danger' | 'success' | 'onInverse' | 'onInverseMuted' | 'onAccent';

export type TxtProps = TextProps & { v?: TypeVariant; tone?: Tone; color?: string; center?: boolean };

/** Текст из дизайн-системы: вариант типографики + цвет из темы. */
export function Txt({ v = 'body', tone, color, center, style, ...rest }: TxtProps) {
  const { c } = useTheme();
  const fallback: Tone = v === 'body' || v === 'callout' ? 'text' : v === 'caption' || v === 'footnote' || v === 'overline' ? 'muted' : 'ink';
  const t = tone ?? fallback;
  const col = color ?? (t === 'accent' ? c.accentText : (c as any)[t]);
  return <RNText {...rest} style={[T[v], { color: col }, center && { textAlign: 'center' }, style]} />;
}

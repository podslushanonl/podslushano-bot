import { View } from 'react-native';
import { useTheme } from '@/theme';
import type { GlassProps } from './Glass';

/**
 * Стекло в браузере: размытие и насыщенность того, что под панелью, светлый блик по краю
 * и мягкая тень — как Liquid Glass на iPhone.
 */
export function Glass({ children, style, radius = 22, strong, tint }: GlassProps) {
  const { c, dark } = useTheme();
  const glass = {
    borderRadius: radius,
    overflow: 'hidden',
    backgroundColor: tint || (strong ? c.glassFillStrong : c.glassFill),
    backdropFilter: `blur(${strong ? 30 : 22}px) saturate(${dark ? 150 : 185}%)`,
    WebkitBackdropFilter: `blur(${strong ? 30 : 22}px) saturate(${dark ? 150 : 185}%)`,
    borderWidth: 1,
    borderColor: c.glassStroke,
    boxShadow: dark
      ? `inset 0 1px 0 rgba(255,255,255,0.10), 0 10px 30px ${c.glassShadow}`
      : `inset 0 1px 0 rgba(255,255,255,0.9), inset 0 -1px 0 rgba(11,13,18,0.04), 0 10px 30px ${c.glassShadow}`,
  } as any;
  return <View style={[glass, style]}>{children}</View>;
}

import { BlurView } from 'expo-blur';
import { GlassView, isLiquidGlassAvailable } from 'expo-glass-effect';
import { ReactNode } from 'react';
import { Platform, StyleProp, StyleSheet, View, ViewStyle } from 'react-native';
import { useTheme } from '@/theme';

export type GlassProps = {
  children?: ReactNode;
  style?: StyleProp<ViewStyle>;
  radius?: number;
  /** Плотнее стекло — для панелей поверх фото и длинного текста. */
  strong?: boolean;
  /** Стекло реагирует на касание (iOS 26+). */
  interactive?: boolean;
  tint?: string;
};

const liquid = Platform.OS === 'ios' && isLiquidGlassAvailable();

/**
 * Стеклянная поверхность. iOS 26+ — системное Liquid Glass, iOS ниже — размытие,
 * Android — плотная полупрозрачная поверхность (там размытие под контентом дорого обходится).
 */
export function Glass({ children, style, radius = 22, strong, interactive, tint }: GlassProps) {
  const { c, dark } = useTheme();
  const shape = { borderRadius: radius, overflow: 'hidden' as const };
  if (liquid) {
    return (
      <GlassView glassEffectStyle="regular" isInteractive={interactive} tintColor={tint}
        style={[shape, style]}>
        {children}
      </GlassView>
    );
  }
  if (Platform.OS === 'ios') {
    return (
      <BlurView intensity={strong ? 90 : 70} tint={dark ? 'systemChromeMaterialDark' : 'systemChromeMaterialLight'}
        style={[shape, { borderWidth: StyleSheet.hairlineWidth, borderColor: c.glassEdge }, style]}>
        {children}
      </BlurView>
    );
  }
  return (
    <View style={[shape, { backgroundColor: tint || c.glassFillStrong, borderWidth: StyleSheet.hairlineWidth, borderColor: c.glassEdge,
      elevation: 6, shadowColor: c.glassShadow }, style]}>
      {children}
    </View>
  );
}

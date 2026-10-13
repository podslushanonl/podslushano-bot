import * as Haptics from 'expo-haptics';
import { ReactNode } from 'react';
import { Platform, Pressable, PressableProps, StyleProp, ViewStyle } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from 'react-native-reanimated';

const APressable = Animated.createAnimatedComponent(Pressable);

export type TapProps = Omit<PressableProps, 'style' | 'children'> & {
  children?: ReactNode;
  style?: StyleProp<ViewStyle>;
  /** Насколько «проседает» элемент при нажатии. */
  scaleTo?: number;
  haptic?: 'light' | 'medium' | 'select' | false;
};

/** Нажимаемый элемент с пружинной анимацией и лёгкой вибрацией, как в системных приложениях. */
export function Tap({ children, style, scaleTo = 0.97, haptic = 'select', onPressIn, onPressOut, onPress, disabled, ...rest }: TapProps) {
  const s = useSharedValue(1);
  const anim = useAnimatedStyle(() => ({ transform: [{ scale: s.get() }] }));
  return (
    <APressable
      {...rest}
      disabled={disabled}
      accessibilityRole={rest.accessibilityRole ?? 'button'}
      onPressIn={(e) => { s.set(withSpring(scaleTo, { damping: 18, stiffness: 420 })); onPressIn?.(e); }}
      onPressOut={(e) => { s.set(withSpring(1, { damping: 14, stiffness: 300 })); onPressOut?.(e); }}
      onPress={(e) => {
        if (haptic && Platform.OS !== 'web') {
          if (haptic === 'select') Haptics.selectionAsync().catch(() => {});
          else Haptics.impactAsync(haptic === 'medium' ? Haptics.ImpactFeedbackStyle.Medium : Haptics.ImpactFeedbackStyle.Light).catch(() => {});
        }
        onPress?.(e);
      }}
      style={[style, anim, disabled && { opacity: 0.5 }]}>
      {children}
    </APressable>
  );
}

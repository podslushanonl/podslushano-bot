import { useEffect } from 'react';
import { Pressable } from 'react-native';
import Animated, { interpolateColor, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { useTheme } from '@/theme';

/** Переключатель в стиле iOS: оранжевый, когда включён; одинаково выглядит на телефоне и в браузере. */
export function Toggle({ value, onChange, label, disabled }: { value: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  const { c } = useTheme();
  const on = useSharedValue(value ? 1 : 0);
  useEffect(() => { on.set(withTiming(value ? 1 : 0, { duration: 180 })); }, [value, on]);
  const track = useAnimatedStyle(() => ({ backgroundColor: interpolateColor(on.get(), [0, 1], [c.lineStrong, c.accent]) }));
  const thumb = useAnimatedStyle(() => ({ transform: [{ translateX: on.get() * 20 }] }));
  return (
    <Pressable onPress={() => !disabled && onChange(!value)} accessibilityRole="switch" accessibilityLabel={label}
      accessibilityState={{ checked: value, disabled }} hitSlop={8} style={{ opacity: disabled ? 0.5 : 1 }}>
      <Animated.View style={[{ width: 51, height: 31, borderRadius: 16, padding: 2 }, track]}>
        <Animated.View style={[{ width: 27, height: 27, borderRadius: 14, backgroundColor: '#FFFFFF',
          boxShadow: '0 2px 5px rgba(0,0,0,0.18)' } as any, thumb]} />
      </Animated.View>
    </Pressable>
  );
}

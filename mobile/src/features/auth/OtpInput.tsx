import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { TextInput, View } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withRepeat, withSequence, withTiming } from 'react-native-reanimated';
import { radius, useTheme } from '@/theme';
import { Txt } from '@/ui';

export type OtpHandle = { focus: () => void; shake: () => void };

/** Код из отдельных квадратиков. Под ними одно скрытое поле: работает автоподстановка кода из СМС/почты и вставка. */
export const OtpInput = forwardRef<OtpHandle, { value: string; onChange: (v: string) => void; length?: number; error?: boolean; disabled?: boolean }>(
  function OtpInput({ value, onChange, length = 6, error, disabled }, ref) {
    const { c } = useTheme();
    const input = useRef<TextInput>(null);
    const [focused, setFocused] = useState(false);
    const dx = useSharedValue(0);
    const caret = useSharedValue(1);

    useImperativeHandle(ref, () => ({
      focus: () => input.current?.focus(),
      shake: () => { dx.value = withSequence(...[-10, 10, -7, 7, -3, 0].map((v) => withTiming(v, { duration: 55 }))); },
    }));
    useEffect(() => { caret.value = withRepeat(withSequence(withTiming(0, { duration: 450 }), withTiming(1, { duration: 450 })), -1); }, [caret]);
    const shakeStyle = useAnimatedStyle(() => ({ transform: [{ translateX: dx.value }] }));
    const caretStyle = useAnimatedStyle(() => ({ opacity: caret.value }));

    const active = Math.min(value.length, length - 1);
    return (
      <Animated.View style={[{ flexDirection: 'row', gap: 8, justifyContent: 'center' }, shakeStyle]}>
        {Array.from({ length }, (_, i) => {
          const d = value[i] || '';
          const on = focused && i === active && !disabled;
          return (
            <View key={i} style={{ flex: 1, maxWidth: 54, aspectRatio: 0.84, borderRadius: radius.m, alignItems: 'center', justifyContent: 'center',
              backgroundColor: c.bgElevated, borderWidth: on || error ? 2 : 1, borderColor: error ? c.danger : on ? c.accent : d ? c.lineStrong : c.line }}>
              {d ? <Txt v="title1" style={{ fontFamily: 'Onest_600SemiBold', fontVariant: ['tabular-nums'] }}>{d}</Txt>
                : on ? <Animated.View style={[{ width: 2, height: 26, borderRadius: 1, backgroundColor: c.accent }, caretStyle]} /> : null}
            </View>
          );
        })}
        <TextInput ref={input} value={value} editable={!disabled} maxLength={length} keyboardType="number-pad" inputMode="numeric"
          autoComplete="one-time-code" textContentType="oneTimeCode" accessibilityLabel="Код подтверждения" caretHidden
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          onChangeText={(v) => onChange(v.replace(/\D/g, '').slice(0, length))}
          style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, opacity: 0, color: 'transparent', backgroundColor: 'transparent',
            borderWidth: 0, fontSize: 1, outlineStyle: 'none' } as any} />
      </Animated.View>
    );
  });

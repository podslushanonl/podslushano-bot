import { forwardRef, ReactNode } from 'react';
import { TextInput, TextInputProps, View } from 'react-native';
import { radius, type as T, useTheme } from '@/theme';
import { Txt } from './Text';

export const Field = forwardRef<TextInput, TextInputProps & { label?: string; hint?: string; error?: string; left?: ReactNode; multilineHeight?: number }>(
  function Field({ label, hint, error, left, multilineHeight = 130, style, multiline, ...p }, ref) {
    const { c } = useTheme();
    return (
      <View style={{ gap: 7 }}>
        {label ? <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold', marginLeft: 4 }}>{label}</Txt> : null}
        <View style={{ flexDirection: 'row', alignItems: multiline ? 'flex-start' : 'center', gap: 10, backgroundColor: c.bgElevated,
          borderRadius: radius.m, borderWidth: 1, borderColor: error ? c.danger : c.line, paddingHorizontal: 14 }}>
          {left}
          <TextInput ref={ref} placeholderTextColor={c.faint} multiline={multiline} {...p}
            style={[T.body, { flex: 1, color: c.ink, paddingVertical: 14, minHeight: multiline ? multilineHeight : 52,
              textAlignVertical: multiline ? 'top' : 'center', outlineStyle: 'none' } as any, style]} />
        </View>
        {error ? <Txt v="footnote" tone="danger" style={{ marginLeft: 4 }}>{error}</Txt>
          : hint ? <Txt v="footnote" style={{ marginLeft: 4 }}>{hint}</Txt> : null}
      </View>
    );
  });

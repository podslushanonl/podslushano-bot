import { forwardRef, ReactNode, RefObject, useEffect, useState } from 'react';
import { Modal, Pressable, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { CodeSent } from '@/api/auth';
import { radius, type as T, useTheme } from '@/theme';
import { Button, Flag, Glass, Icon, Tap, Txt } from '@/ui';
import { OtpHandle, OtpInput } from './OtpInput';
import { COUNTRIES, formatPhone, parsePhone, phoneDigits, phoneReady, PhoneCountry, prettyPhone } from './phone';

// Общие части экранов входа и привязки: поле «номер с флагом / почта» и шаг с кодом из 6 цифр.

export const RESEND_SEC = 60;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export type Contact = { mode: 'phone' | 'email'; country: PhoneCountry; digits: string; email: string };
export const emptyContact = (mode: Contact['mode'] = 'phone'): Contact => ({ mode, country: COUNTRIES[0], digits: '', email: '' });
export const contactReady = (v: Contact) => (v.mode === 'phone' ? phoneReady(v.digits, v.country) : EMAIL.test(v.email.trim()));
export const contactTarget = (v: Contact) => (v.mode === 'phone' ? { phone: v.digits, cc: v.country.cc } : { email: v.email.trim() });

/** Поле ввода: номер с выбором страны и маской или почта. */
export const ContactInput = forwardRef<TextInput, {
  value: Contact; onChange: (v: Contact) => void; onSubmit: () => void; error?: boolean; autoFocus?: boolean;
}>(function ContactInput({ value, onChange, onSubmit, error, autoFocus }, ref) {
  const { c } = useTheme();
  const [picker, setPicker] = useState(false);
  const inputStyle = [T.title3, { flex: 1, color: c.ink, paddingVertical: 16, fontFamily: 'Onest_500Medium', letterSpacing: 0.3,
    minWidth: 0, width: '100%', outlineStyle: 'none' } as any];
  const focus = () => setTimeout(() => (ref as RefObject<TextInput | null>)?.current?.focus(), 100);
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: c.bgElevated, borderRadius: radius.l,
      borderWidth: 1, borderColor: error ? c.danger : c.line, paddingHorizontal: 14, minHeight: 60, gap: 10 }}>
      {value.mode === 'phone' ? (
        <>
          <Tap onPress={() => setPicker(true)} scaleTo={0.94} accessibilityLabel={`Страна: ${value.country.name}`}
            style={{ flexDirection: 'row', alignItems: 'center', gap: 7, paddingVertical: 10 }}>
            <Flag code={value.country.flag} />
            <Txt v="bodyStrong" style={{ fontVariant: ['tabular-nums'] }}>+{value.country.cc}</Txt>
            <Icon name="down" thin size={14} color={c.muted} />
          </Tap>
          <View style={{ width: 1, height: 26, backgroundColor: c.line }} />
          <TextInput ref={ref} value={formatPhone(value.digits, value.country)} placeholder={value.country.sample} placeholderTextColor={c.faint}
            onChangeText={(t) => { const p = parsePhone(t, value.country); onChange({ ...value, country: p.country, digits: p.digits }); }}
            keyboardType="phone-pad" inputMode="tel" autoComplete="tel-national" textContentType="telephoneNumber" returnKeyType="next"
            onSubmitEditing={onSubmit} accessibilityLabel="Номер телефона" autoFocus={autoFocus} style={inputStyle} />
          <CountryPicker visible={picker} value={value.country} onClose={() => setPicker(false)}
            onPick={(x) => { onChange({ ...value, country: x, digits: phoneDigits(value.digits, x) }); setPicker(false); focus(); }} />
        </>
      ) : (
        <>
          <Icon name="mail" thin size={20} color={c.muted} />
          <TextInput ref={ref} value={value.email} placeholder="you@example.com" placeholderTextColor={c.faint}
            onChangeText={(t) => onChange({ ...value, email: t })} keyboardType="email-address" inputMode="email" autoCapitalize="none"
            autoComplete="email" textContentType="emailAddress" returnKeyType="next" onSubmitEditing={onSubmit}
            accessibilityLabel="Почта" autoFocus={autoFocus} style={inputStyle} />
        </>
      )}
    </View>
  );
});

function CountryPicker({ visible, value, onPick, onClose }: { visible: boolean; value: PhoneCountry; onPick: (c: PhoneCountry) => void; onClose: () => void }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={{ flex: 1, backgroundColor: c.scrim, justifyContent: 'flex-end', padding: 10, paddingBottom: insets.bottom + 10 }} onPress={onClose}
        accessibilityLabel="Закрыть">
        <Pressable onPress={() => {}}>
          <Glass radius={radius.xl} strong>
            <Txt v="footnote" center style={{ paddingTop: 14, paddingBottom: 6 }}>Страна номера</Txt>
            {COUNTRIES.map((x) => (
              <Tap key={x.cc} onPress={() => onPick(x)} scaleTo={0.98} accessibilityLabel={`${x.name}, +${x.cc}`}
                style={{ flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 16, paddingHorizontal: 20, borderTopWidth: 1, borderTopColor: c.line }}>
                <Flag code={x.flag} size={26} />
                <Txt v="bodyStrong" style={{ flex: 1 }}>{x.name}</Txt>
                <Txt v="body" tone="muted" style={{ fontVariant: ['tabular-nums'] }}>+{x.cc}</Txt>
                <View style={{ width: 20, alignItems: 'flex-end' }}>{x.cc === value.cc ? <Icon name="check" size={18} color={c.accent} /> : null}</View>
              </Tap>
            ))}
          </Glass>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/** Обратный отсчёт до повторной отправки кода. */
export function useCountdown() {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);
  return [left, setLeft] as const;
}

/** Шаг «введите код»: куда отправили, квадратики, повторная отправка и «изменить». */
export function CodeStep({ sent, otp, code, onCode, err, busy, left, onResend, onEdit, title = 'Введите код', children }: {
  sent: CodeSent; otp: RefObject<OtpHandle | null>; code: string; onCode: (v: string) => void; err: string; busy: boolean;
  left: number; onResend: () => void; onEdit: () => void; title?: string; children?: ReactNode;
}) {
  return (
    <>
      <View style={{ gap: 10, marginTop: 12 }}>
        <Txt v="display">{title}</Txt>
        <View style={{ gap: 2 }}>
          <Txt v="callout" tone="muted">{sent.kind === 'phone' ? 'Отправили его в SMS на номер' : 'Отправили его письмом на почту'}</Txt>
          <Txt v="bodyStrong" style={{ fontVariant: ['tabular-nums'] }}>{sent.kind === 'phone' ? prettyPhone(sent.to) : sent.to}</Txt>
        </View>
      </View>
      <OtpInput ref={otp} value={code} onChange={onCode} error={!!err} disabled={busy} />
      {err ? <Txt v="callout" tone="danger" center>{err}</Txt> : null}
      {children}
      <View style={{ alignItems: 'center', gap: 4 }}>
        {left > 0 ? (
          <Txt v="subhead" tone="muted" style={{ fontVariant: ['tabular-nums'] }}>Новый код можно запросить через 0:{String(left).padStart(2, '0')}</Txt>
        ) : (
          <Button title="Отправить код ещё раз" kind="plain" size="s" full={false} style={{ alignSelf: 'center' }} loading={busy} onPress={onResend} />
        )}
        <Button title={sent.kind === 'phone' ? 'Изменить номер' : 'Изменить почту'} kind="plain" size="s" full={false} style={{ alignSelf: 'center' }}
          onPress={onEdit} />
      </View>
    </>
  );
}

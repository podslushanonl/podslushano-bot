import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Linking, Modal, Platform, Pressable, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { authMethods, CodeSent, pollTelegram, requestCode, startTelegram, useAuth, verifyCode } from '@/api/auth';
import { OtpHandle, OtpInput } from '@/features/auth/OtpInput';
import { COUNTRIES, formatPhone, phoneDigits, phoneReady, PhoneCountry, prettyPhone } from '@/features/auth/phone';
import { radius, type as T, useTheme } from '@/theme';
import { Button, Flag, Glass, Icon, Img, PageScreen, Segmented, Tap, Txt } from '@/ui';

const PENDING = 'pn_tg_login';
const RESEND_SEC = 60;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/** Вход и регистрация одним шагом: номер телефона или почта → код из 6 цифр. Аккаунт создаётся при первом входе. */
export default function Login() {
  const { c } = useTheme();
  const { user } = useAuth();
  const methods = useQuery({ queryKey: ['auth-methods'], queryFn: authMethods, staleTime: 60_000 });
  const phoneOn = methods.data?.phone ?? false;

  const [mode, setMode] = useState<'phone' | 'email'>('phone');
  const [country, setCountry] = useState<PhoneCountry>(COUNTRIES[0]);
  const [picker, setPicker] = useState(false);
  const [digits, setDigits] = useState('');
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState<CodeSent | null>(null);
  const [code, setCode] = useState('');
  const [left, setLeft] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [tgWait, setTgWait] = useState(false);
  const otp = useRef<OtpHandle>(null);
  const field = useRef<TextInput>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const usePhone = phoneOn && mode === 'phone';
  const ready = usePhone ? phoneReady(digits, country) : EMAIL.test(email.trim());

  useEffect(() => {
    if (!user) return;
    if (!user.name) router.replace('/profile-edit');
    else if (router.canGoBack()) router.back();
    else router.replace('/');
  }, [user]);
  // Обратный отсчёт до повторной отправки кода
  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);

  const send = async () => {
    if (busy || !ready) return;
    setBusy(true); setErr('');
    try {
      const d = await requestCode(usePhone ? { phone: digits, cc: country.cc } : { email: email.trim() });
      setSent(d); setCode(''); setLeft(RESEND_SEC);
      setTimeout(() => otp.current?.focus(), 350);
    } catch (e: any) { setErr(e?.message || 'Не получилось отправить код.'); } finally { setBusy(false); }
  };
  const check = async (v: string) => {
    if (!sent || busy) return;
    setBusy(true); setErr('');
    try { await verifyCode(sent, v); } catch (e: any) {
      setErr(e?.message || 'Неверный код.'); otp.current?.shake(); setCode('');
      setTimeout(() => otp.current?.focus(), 50);
    } finally { setBusy(false); }
  };
  const onCode = (v: string) => { setCode(v); setErr(''); if (v.length === 6) check(v); };

  // Ещё один способ: вход через Telegram-бота
  const stopPolling = () => { if (timer.current) clearInterval(timer.current); timer.current = null; setTgWait(false); AsyncStorage.removeItem(PENDING).catch(() => {}); };
  const poll = (nonce: string, started: number) => {
    if (timer.current) clearInterval(timer.current);
    setTgWait(true);
    timer.current = setInterval(async () => {
      try { if (await pollTelegram(nonce) || Date.now() - started > 10 * 60_000) stopPolling(); }
      catch (e: any) { stopPolling(); setErr(e?.message || ''); }
    }, 2000);
  };
  useEffect(() => {
    AsyncStorage.getItem(PENDING).then((v) => {
      if (!v) return;
      const { nonce, started } = JSON.parse(v);
      if (Date.now() - started < 10 * 60_000) poll(nonce, started); else AsyncStorage.removeItem(PENDING);
    }).catch(() => {});
    return () => { if (timer.current) clearInterval(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const telegram = async () => {
    setErr('');
    try {
      const { nonce, url } = await startTelegram();
      const started = Date.now();
      AsyncStorage.setItem(PENDING, JSON.stringify({ nonce, started })).catch(() => {});
      poll(nonce, started);
      if (Platform.OS === 'web') (globalThis as any).open(url, '_blank', 'noopener'); else Linking.openURL(url);
    } catch (e: any) { setErr(e?.message || 'Не получилось.'); }
  };

  const inputStyle = [T.title3, { flex: 1, color: c.ink, paddingVertical: 16, fontFamily: 'Onest_500Medium', letterSpacing: 0.3, minWidth: 0, width: '100%', outlineStyle: 'none' } as any];

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen contentStyle={{ gap: 22 }}>
        {!sent ? (
          <>
            <View style={{ gap: 10, marginTop: 12 }}>
              <Txt v="display">Вход</Txt>
              <Txt v="callout" tone="muted">
                {usePhone ? 'Введите номер телефона — пришлём SMS с кодом подтверждения.' : 'Введите почту — пришлём код подтверждения.'}
                {' '}Пароль не нужен, аккаунт создастся сам.
              </Txt>
            </View>

            {phoneOn ? <Segmented value={mode} onChange={(m) => { setMode(m); setErr(''); setTimeout(() => field.current?.focus(), 50); }}
              items={[{ key: 'phone', title: 'Телефон' }, { key: 'email', title: 'Почта' }]} /> : null}

            <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: c.bgElevated, borderRadius: radius.l,
              borderWidth: 1, borderColor: err ? c.danger : c.line, paddingHorizontal: 14, minHeight: 60, gap: 10 }}>
              {usePhone ? (
                <>
                  <Tap onPress={() => setPicker(true)} scaleTo={0.94} accessibilityLabel={`Страна: ${country.name}`}
                    style={{ flexDirection: 'row', alignItems: 'center', gap: 7, paddingVertical: 10 }}>
                    <Flag code={country.flag} />
                    <Txt v="bodyStrong" style={{ fontVariant: ['tabular-nums'] }}>+{country.cc}</Txt>
                    <Icon name="down" thin size={14} color={c.muted} />
                  </Tap>
                  <View style={{ width: 1, height: 26, backgroundColor: c.line }} />
                  <TextInput ref={field} value={formatPhone(digits, country)} placeholder={country.sample} placeholderTextColor={c.faint}
                    onChangeText={(v) => { setDigits(phoneDigits(v, country)); setErr(''); }} keyboardType="phone-pad" inputMode="tel"
                    autoComplete="tel-national" textContentType="telephoneNumber" returnKeyType="next" onSubmitEditing={send}
                    accessibilityLabel="Номер телефона" autoFocus style={inputStyle} />
                </>
              ) : (
                <>
                  <Icon name="mail" thin size={20} color={c.muted} />
                  <TextInput ref={field} value={email} placeholder="you@example.com" placeholderTextColor={c.faint}
                    onChangeText={(v) => { setEmail(v); setErr(''); }} keyboardType="email-address" inputMode="email" autoCapitalize="none"
                    autoComplete="email" textContentType="emailAddress" returnKeyType="next" onSubmitEditing={send}
                    accessibilityLabel="Почта" autoFocus={!phoneOn} style={inputStyle} />
                </>
              )}
            </View>
            {err ? <Txt v="callout" tone="danger" style={{ marginTop: -10 }}>{err}</Txt> : null}

            <Button title="Далее" kind="accent" loading={busy} disabled={!ready} onPress={send} />

            <View style={{ alignItems: 'center', gap: 6, marginTop: 4 }}>
              {tgWait ? (
                <View style={{ alignItems: 'center', gap: 8 }}>
                  <Txt v="callout" tone="muted" center>Подтвердите вход в боте и вернитесь сюда — вход произойдёт сам.</Txt>
                  <Button title="Отменить" kind="plain" size="s" full={false} onPress={stopPolling} />
                </View>
              ) : (
                <Tap onPress={telegram} scaleTo={0.97} style={{ flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 8 }}
                  accessibilityLabel="Войти через Telegram">
                  <Img source={require('@assets/images/social/telegram.png')} style={{ width: 20, height: 20, backgroundColor: 'transparent' }} />
                  <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>Войти через Telegram</Txt>
                </Tap>
              )}
            </View>
          </>
        ) : (
          <>
            <View style={{ gap: 10, marginTop: 12 }}>
              <Txt v="display">Введите код</Txt>
              <View style={{ gap: 2 }}>
                <Txt v="callout" tone="muted">{sent.kind === 'phone' ? 'Отправили его в SMS на номер' : 'Отправили его письмом на почту'}</Txt>
                <Txt v="bodyStrong" style={{ fontVariant: ['tabular-nums'] }}>{sent.kind === 'phone' ? prettyPhone(sent.to) : sent.to}</Txt>
              </View>
            </View>
            <OtpInput ref={otp} value={code} onChange={onCode} error={!!err} disabled={busy} />
            {err ? <Txt v="callout" tone="danger" center>{err}</Txt> : null}
            <View style={{ alignItems: 'center', gap: 4 }}>
              {left > 0 ? (
                <Txt v="subhead" tone="muted" style={{ fontVariant: ['tabular-nums'] }}>Новый код можно запросить через 0:{String(left).padStart(2, '0')}</Txt>
              ) : (
                <Button title="Отправить код ещё раз" kind="plain" size="s" full={false} style={{ alignSelf: 'center' }} loading={busy} onPress={send} />
              )}
              <Button title={sent.kind === 'phone' ? 'Изменить номер' : 'Изменить почту'} kind="plain" size="s" full={false} style={{ alignSelf: 'center' }}
                onPress={() => { setSent(null); setCode(''); setErr(''); setTimeout(() => field.current?.focus(), 100); }} />
            </View>
          </>
        )}
        <Txt v="footnote" center style={{ marginTop: 8 }}>Входя, вы соглашаетесь с условиями и политикой конфиденциальности podslushano.nl.</Txt>
      </PageScreen>
      <CountryPicker visible={picker} value={country} onClose={() => setPicker(false)}
        onPick={(x) => { setCountry(x); setDigits((d) => phoneDigits(d, x)); setPicker(false); setTimeout(() => field.current?.focus(), 100); }} />
    </KeyboardAvoidingView>
  );
}

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

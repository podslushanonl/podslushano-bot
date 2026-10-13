import AsyncStorage from '@react-native-async-storage/async-storage';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Linking, Platform, TextInput, View } from 'react-native';
import { pollTelegram, requestCode, startTelegram, useAuth, verifyCode } from '@/api/auth';
import { radius, useTheme } from '@/theme';
import { Button, Field, Icon, Img, PageScreen, Txt } from '@/ui';

const PENDING = 'pn_tg_login';

/** Вход и регистрация одним шагом: аккаунт создаётся при первом входе. */
export default function Login() {
  const { c } = useTheme();
  const { user } = useAuth();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'start' | 'code' | 'tg'>('start');
  const [busy, setBusy] = useState<'' | 'mail' | 'code' | 'tg'>('');
  const [err, setErr] = useState('');
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const codeRef = useRef<TextInput>(null);

  const stopPolling = () => { if (timer.current) clearInterval(timer.current); timer.current = null; AsyncStorage.removeItem(PENDING).catch(() => {}); };
  // Ждём подтверждения в боте. Nonce сохраняем, чтобы продолжить после возврата из Telegram
  const poll = (nonce: string, started: number) => {
    if (timer.current) clearInterval(timer.current);
    setStep('tg');
    timer.current = setInterval(async () => {
      try { if (await pollTelegram(nonce) || Date.now() - started > 10 * 60_000) stopPolling(); }
      catch (e: any) { stopPolling(); setErr(e?.message || ''); setStep('start'); }
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
  useEffect(() => {
    if (!user) return;
    if (!user.name) router.replace('/profile-edit');
    else if (router.canGoBack()) router.back();
    else router.replace('/');
  }, [user]);

  const run = async (kind: typeof busy, fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(kind); setErr('');
    try { await fn(); } catch (e: any) { setErr(e?.message || 'Ошибка. Попробуйте ещё раз.'); } finally { setBusy(''); }
  };
  const sendCode = () => run('mail', async () => { await requestCode(email.trim()); setStep('code'); setTimeout(() => codeRef.current?.focus(), 300); });
  const check = (v = code) => run('code', () => verifyCode(email.trim(), v));
  const tg = () => run('tg', async () => {
    const { nonce, url } = await startTelegram();
    const started = Date.now();
    AsyncStorage.setItem(PENDING, JSON.stringify({ nonce, started })).catch(() => {});
    poll(nonce, started);
    // В браузере открываем Telegram в новой вкладке, чтобы страница приложения не выгрузилась
    if (Platform.OS === 'web') (globalThis as any).open(url, '_blank', 'noopener'); else Linking.openURL(url);
  });

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen title="Вход">
        <View style={{ gap: 8, marginTop: 8 }}>
          <View style={{ width: 64, height: 64, borderRadius: 22, backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="person" size={30} color={c.onAccent} />
          </View>
          <Txt v="title1">Вход в podslushano</Txt>
          <Txt v="callout" tone="muted">Пароль не нужен. Если аккаунта ещё нет — он создастся сам.</Txt>
        </View>

        {step === 'start' ? (
          <>
            <Field label="Почта" value={email} onChangeText={setEmail} placeholder="you@example.com" keyboardType="email-address"
              autoCapitalize="none" autoComplete="email" returnKeyType="send" onSubmitEditing={sendCode} />
            <Button title="Получить код" kind="primary" loading={busy === 'mail'} disabled={!/.+@.+\..+/.test(email.trim())} onPress={sendCode} />
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
              <View style={{ flex: 1, height: 1, backgroundColor: c.line }} />
              <Txt v="footnote">или</Txt>
              <View style={{ flex: 1, height: 1, backgroundColor: c.line }} />
            </View>
            <Button title="Войти через Telegram" kind="secondary" loading={busy === 'tg'} onPress={tg} />
          </>
        ) : step === 'code' ? (
          <View style={{ gap: 14 }}>
            <Txt v="callout" tone="ink">Код отправлен на <Txt v="bodyStrong">{email.trim()}</Txt>. Он действует 15 минут.</Txt>
            <TextInput ref={codeRef} value={code} keyboardType="number-pad" autoComplete="one-time-code" textContentType="oneTimeCode" maxLength={6}
              onChangeText={(v) => { const d = v.replace(/\D/g, '').slice(0, 6); setCode(d); if (d.length === 6) check(d); }}
              placeholder="000000" placeholderTextColor={c.faint} accessibilityLabel="Код из письма"
              style={{ fontFamily: 'Unbounded_600SemiBold', fontSize: 30, letterSpacing: 12, textAlign: 'center', color: c.ink, backgroundColor: c.bgElevated,
                borderRadius: radius.l, borderWidth: 1, borderColor: c.line, paddingVertical: 16, outlineStyle: 'none' } as any} />
            <Button title="Войти" kind="primary" loading={busy === 'code'} disabled={code.length !== 6} onPress={() => check()} />
            <Button title="Другая почта или новый код" kind="plain" onPress={() => { setStep('start'); setCode(''); }} />
          </View>
        ) : (
          <View style={{ gap: 14, backgroundColor: c.bgElevated, borderRadius: radius.xl, padding: 18, borderWidth: 1, borderColor: c.line }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
              <Img source={require('@assets/images/social/telegram.png')} style={{ width: 40, height: 40, backgroundColor: 'transparent' }} />
              <Txt v="headline" style={{ flex: 1 }}>Подтвердите вход в Telegram</Txt>
            </View>
            <Txt v="callout" tone="muted">Откроется наш бот. Нажмите в нём «Запустить» и вернитесь сюда — вход произойдёт сам.</Txt>
            <Button title="Отмена" kind="secondary" size="s" onPress={() => { stopPolling(); setStep('start'); }} />
          </View>
        )}

        {err ? <Txt v="callout" tone="danger">{err}</Txt> : null}
        <Txt v="footnote">Входя, вы соглашаетесь с условиями и политикой конфиденциальности podslushano.nl.</Txt>
      </PageScreen>
    </KeyboardAvoidingView>
  );
}

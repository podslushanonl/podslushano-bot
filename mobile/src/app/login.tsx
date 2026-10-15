import AsyncStorage from '@react-native-async-storage/async-storage';
import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Linking, Platform, TextInput, View } from 'react-native';
import { authMethods, CodeSent, pollTelegram, requestCode, startTelegram, useAuth, verifyCode } from '@/api/auth';
import { CodeStep, Contact, ContactInput, contactReady, contactTarget, emptyContact, RESEND_SEC, useCountdown } from '@/features/auth/ContactForm';
import { OtpHandle } from '@/features/auth/OtpInput';
import { Button, Img, PageScreen, Segmented, Tap, Txt } from '@/ui';

const PENDING = 'pn_tg_login';

/** Вход и регистрация одним шагом: номер телефона или почта → код из 6 цифр. Аккаунт создаётся при первом входе. */
export default function Login() {
  const { user } = useAuth();
  const methods = useQuery({ queryKey: ['auth-methods'], queryFn: authMethods, staleTime: 60_000 });
  const phoneOn = methods.data?.phone ?? false;

  const [contact, setContact] = useState<Contact>(emptyContact());
  const [sent, setSent] = useState<CodeSent | null>(null);
  const [code, setCode] = useState('');
  const [left, setLeft] = useCountdown();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [tgWait, setTgWait] = useState(false);
  const otp = useRef<OtpHandle>(null);
  const field = useRef<TextInput>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Пока вход по номеру выключен на сервере — только почта
  const value: Contact = phoneOn ? contact : { ...contact, mode: 'email' };
  const ready = contactReady(value);

  useEffect(() => {
    if (!user) return;
    if (!user.name) router.replace('/profile-edit');
    else if (router.canGoBack()) router.back();
    else router.replace('/');
  }, [user]);

  const send = async () => {
    if (busy || !ready) return;
    setBusy(true); setErr('');
    try {
      const d = await requestCode(contactTarget(value));
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


  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen contentStyle={{ gap: 22 }}>
        {!sent ? (
          <>
            <View style={{ gap: 10, marginTop: 12 }}>
              <Txt v="display">Вход</Txt>
              <Txt v="callout" tone="muted">
                {value.mode === 'phone' ? 'Введите номер телефона — пришлём SMS с кодом подтверждения.' : 'Введите почту — пришлём код подтверждения.'}
                {' '}Пароль не нужен, аккаунт создастся сам.
              </Txt>
            </View>

            {phoneOn ? <Segmented value={contact.mode} onChange={(m) => { setContact({ ...contact, mode: m }); setErr(''); setTimeout(() => field.current?.focus(), 50); }}
              items={[{ key: 'phone', title: 'Телефон' }, { key: 'email', title: 'Почта' }]} /> : null}

            <ContactInput ref={field} value={value} onChange={(v) => { setContact(v); setErr(''); }} onSubmit={send} error={!!err} autoFocus />
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
          <CodeStep sent={sent} otp={otp} code={code} onCode={onCode} err={err} busy={busy} left={left} onResend={send}
            onEdit={() => { setSent(null); setCode(''); setErr(''); setTimeout(() => field.current?.focus(), 100); }} />
        )}
        <Txt v="footnote" center style={{ marginTop: 8 }}>Входя, вы соглашаетесь с условиями и политикой конфиденциальности podslushano.nl.</Txt>
      </PageScreen>
    </KeyboardAvoidingView>
  );
}

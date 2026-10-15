import { router, useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, TextInput, View } from 'react-native';
import { CodeSent, linkCheck, linkStart, useAuth } from '@/api/auth';
import { ApiError } from '@/api/client';
import { CodeStep, Contact, ContactInput, contactReady, contactTarget, emptyContact, RESEND_SEC, useCountdown } from '@/features/auth/ContactForm';
import { OtpHandle } from '@/features/auth/OtpInput';
import { prettyPhone } from '@/features/auth/phone';
import { Button, PageScreen, Txt, useToast } from '@/ui';

/** Привязать к аккаунту номер телефона или почту: тогда войти можно любым из способов — в один и тот же профиль. */
export default function Link() {
  const { kind } = useLocalSearchParams<{ kind?: string }>();
  const mode = kind === 'email' ? 'email' : 'phone';
  const { user } = useAuth();
  const toast = useToast();
  const [contact, setContact] = useState<Contact>(emptyContact(mode));
  const [sent, setSent] = useState<CodeSent | null>(null);
  const [code, setCode] = useState('');
  const [left, setLeft] = useCountdown();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [taken, setTaken] = useState<string | null>(null);   // номер/почта у другого аккаунта: имя того аккаунта
  const otp = useRef<OtpHandle>(null);
  const field = useRef<TextInput>(null);
  const current = mode === 'phone' ? (user?.phone ? prettyPhone(user.phone) : '') : user?.email || '';
  const what = mode === 'phone' ? 'номер' : 'почту';

  const send = async () => {
    if (busy || !contactReady(contact)) return;
    setBusy(true); setErr(''); setTaken(null);
    try {
      const d = await linkStart(contactTarget(contact));
      setSent(d); setCode(''); setLeft(RESEND_SEC);
      setTimeout(() => otp.current?.focus(), 350);
    } catch (e: any) { setErr(e?.message || 'Не получилось отправить код.'); } finally { setBusy(false); }
  };
  const finish = async (v: string, move = false) => {
    if (!sent || busy) return;
    setBusy(true); setErr('');
    try {
      await linkCheck(sent, v, move);
      toast(mode === 'phone' ? 'Номер привязан' : 'Почта привязана');
      if (router.canGoBack()) router.back(); else router.replace('/settings');
    } catch (e: any) {
      if (e instanceof ApiError && e.status === 409 && e.data?.taken) { setTaken(e.data.taken.name || ''); return; }
      setErr(e?.message || 'Неверный код.'); otp.current?.shake(); setCode('');
      setTimeout(() => otp.current?.focus(), 50);
    } finally { setBusy(false); }
  };
  const onCode = (v: string) => { setCode(v); setErr(''); setTaken(null); if (v.length === 6) finish(v); };
  const move = () => {
    const text = `Он перестанет быть способом входа в аккаунт${taken ? ` «${taken}»` : ''}. Публикации того аккаунта останутся в нём.`;
    if (Platform.OS === 'web') { if ((globalThis as any).confirm(text)) finish(code, true); return; }
    Alert.alert(`Перенести ${what} сюда?`, text, [{ text: 'Отмена', style: 'cancel' }, { text: 'Перенести', onPress: () => finish(code, true) }]);
  };

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen contentStyle={{ gap: 22 }}>
        {!sent ? (
          <>
            <View style={{ gap: 10, marginTop: 12 }}>
              <Txt v="display">{mode === 'phone' ? (current ? 'Другой номер' : 'Привязать номер') : (current ? 'Другая почта' : 'Привязать почту')}</Txt>
              <Txt v="callout" tone="muted">
                {current ? `Сейчас: ${current}. ` : ''}
                {mode === 'phone' ? 'Пришлём SMS с кодом. Потом сможете входить по этому номеру в этот же аккаунт.'
                  : 'Пришлём письмо с кодом. Потом сможете входить по этой почте в этот же аккаунт.'}
              </Txt>
            </View>
            <ContactInput ref={field} value={contact} onChange={(v) => { setContact(v); setErr(''); }} onSubmit={send} error={!!err} autoFocus />
            {err ? <Txt v="callout" tone="danger" style={{ marginTop: -10 }}>{err}</Txt> : null}
            <Button title="Получить код" kind="accent" loading={busy} disabled={!contactReady(contact)} onPress={send} />
          </>
        ) : (
          <CodeStep sent={sent} otp={otp} code={code} onCode={onCode} err={err} busy={busy} left={left} onResend={send}
            title="Подтвердите" onEdit={() => { setSent(null); setCode(''); setErr(''); setTaken(null); setTimeout(() => field.current?.focus(), 100); }}>
            {taken !== null ? (
              <View style={{ gap: 12 }}>
                <Txt v="callout" tone="ink" center>
                  {mode === 'phone' ? 'Этот номер уже привязан' : 'Эта почта уже привязана'} к другому аккаунту{taken ? ` — «${taken}»` : ''}.
                  {' '}Перенести сюда?
                </Txt>
                <Button title="Перенести сюда" kind="accent" loading={busy} onPress={move} />
              </View>
            ) : null}
          </CodeStep>
        )}
      </PageScreen>
    </KeyboardAvoidingView>
  );
}

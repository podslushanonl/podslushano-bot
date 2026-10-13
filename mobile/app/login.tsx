import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { KeyboardAvoidingView, Linking, Platform, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button, Card, Eyebrow, H, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { pollTelegram, requestCode, startTelegram, useAuth, verifyCode } from '@/lib/auth';

const PENDING = 'pn_tg_login';

/** Вход и регистрация одним шагом: аккаунт создаётся при первом входе. */
export default function Login() {
  const { user } = useAuth();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'start' | 'code' | 'tg'>('start');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => { if (timer.current) clearInterval(timer.current); timer.current = null; AsyncStorage.removeItem(PENDING).catch(() => {}); };

  // Опрос бота: вход подтверждён → готово. Nonce хранится, чтобы продолжить после возврата из Telegram
  const poll = (nonce: string, started: number) => {
    if (timer.current) clearInterval(timer.current);
    setStep('tg');
    timer.current = setInterval(async () => {
      try {
        if (await pollTelegram(nonce) || Date.now() - started > 10 * 60_000) stopPolling();
      } catch (e: any) { stopPolling(); setErr(e?.message || ''); setStep('start'); }
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
    if (user) router.replace(user.name && user.city ? '/(tabs)/more' : '/profile');
  }, [user]);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true); setErr('');
    try { await fn(); } catch (e: any) { setErr(e?.message || 'Ошибка. Попробуйте ещё раз.'); } finally { setBusy(false); }
  };

  const sendCode = () => { if (!busy) run(async () => { await requestCode(email.trim()); setStep('code'); }); };
  const check = () => { if (!busy) run(() => verifyCode(email.trim(), code)); };
  const tg = () => { if (!busy) run(async () => {
    const { nonce, url } = await startTelegram();
    const started = Date.now();
    // Сохранение nonce — только для продолжения после возврата; если хранилище недоступно, вход всё равно идёт
    AsyncStorage.setItem(PENDING, JSON.stringify({ nonce, started })).catch(() => {});
    poll(nonce, started);
    // В браузере открываем Telegram в новой вкладке, чтобы страница приложения не выгрузилась
    if (Platform.OS === 'web') window.open(url, '_blank', 'noopener'); else Linking.openURL(url);
  }); };

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
      <ScrollView contentContainerStyle={{ padding: 20, gap: 16 }} keyboardShouldPersistTaps="handled">
        <Eyebrow>Мой podslushano</Eyebrow>
        <H size={26}>Вход и регистрация</H>
        <P muted>Пароль не нужен. Если аккаунта ещё нет, он создастся автоматически.</P>

        {step === 'start' && (
          <>
            <Card>
              <Text style={st.label}>Почта</Text>
              <TextInput value={email} onChangeText={setEmail} placeholder="you@example.com" placeholderTextColor={C.muted}
                keyboardType="email-address" autoCapitalize="none" autoComplete="email" style={st.input} />
              <Button title={busy ? 'Отправляем…' : 'Получить код'} onPress={sendCode} disabled={busy} />
            </Card>
            <Text style={st.or}>или</Text>
            <Button title="Войти через Telegram" soft onPress={tg} disabled={busy} />
          </>
        )}

        {step === 'code' && (
          <Card>
            <P>Мы отправили код на <Text style={{ fontWeight: '700' }}>{email.trim()}</Text>. Он действует 15 минут.</P>
            <TextInput value={code} onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))} placeholder="000000"
              placeholderTextColor={C.muted} keyboardType="number-pad" autoComplete="one-time-code" style={[st.input, st.code]} />
            <Button title={busy ? 'Проверяем…' : 'Войти'} onPress={check} disabled={busy} />
            <Text style={st.link} onPress={() => { setStep('start'); setCode(''); }}>Другая почта или отправить код ещё раз</Text>
          </Card>
        )}

        {step === 'tg' && (
          <Card>
            <H size={18}>Подтвердите вход в Telegram</H>
            <P muted>Откроется наш бот. Нажмите в нём «Запустить», а потом вернитесь сюда: вход произойдёт сам.</P>
            <Text style={st.link} onPress={() => { stopPolling(); setStep('start'); }}>Отмена</Text>
          </Card>
        )}

        {err ? <Text style={st.err}>{err}</Text> : null}
        <View style={{ height: 8 }} />
        <P muted>Входя, вы соглашаетесь с условиями и политикой конфиденциальности podslushano.nl.</P>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const st = StyleSheet.create({
  label: { fontSize: 13, fontWeight: '700', color: C.muted },
  input: { backgroundColor: C.bg, borderRadius: 14, borderWidth: 1, borderColor: C.line, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16, color: C.ink },
  code: { fontSize: 28, letterSpacing: 10, textAlign: 'center', fontWeight: '800' },
  or: { textAlign: 'center', color: C.muted },
  link: { color: C.accent, fontWeight: '600', textAlign: 'center', paddingVertical: 6 },
  err: { color: C.warn, fontWeight: '600' },
});

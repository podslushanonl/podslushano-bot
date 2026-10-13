import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, Text } from 'react-native';
import { Button, Card, Eyebrow, H, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { acceptRules, routeForError } from '@/lib/community';

const RULES = [
  'Уважайте друг друга: без оскорблений, угроз, травли и дискриминации.',
  'Без мата и контента 18+.',
  'Без политики и споров о ней. Мы здесь, чтобы помогать друг другу жить в Нидерландах.',
  'Без спама и навязчивой рекламы. Реклама бизнеса — через раздел «Для бизнеса».',
  'Не публикуйте чужие личные данные: адреса, телефоны, документы, фото без согласия.',
  'Никакого мошенничества и продажи запрещённого.',
  'Нарушения удаляем, нарушителей блокируем. Мы не терпим недопустимый контент.',
];

export default function Rules() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const accept = async () => {
    setBusy(true); setErr('');
    try { await acceptRules(); router.back(); }
    catch (e: any) { if (!routeForError(e)) setErr(e?.message || 'Ошибка'); }
    finally { setBusy(false); }
  };
  return (
    <ScrollView contentContainerStyle={{ padding: 20, gap: 14 }}>
      <Eyebrow>Сообщество podslushano</Eyebrow>
      <H size={26}>Правила общения</H>
      <Card>
        {RULES.map((r, i) => <P key={i}>{i + 1}. {r}</P>)}
      </Card>
      <P muted>Увидели нарушение? Нажмите на сообщение и подержите — появится «Пожаловаться». Модераторы проверят. Там же можно скрыть сообщения человека.</P>
      <Button title={busy ? 'Сохраняем…' : 'Принимаю правила'} onPress={accept} disabled={busy} />
      {err ? <Text style={{ color: C.warn }}>{err}</Text> : null}
    </ScrollView>
  );
}

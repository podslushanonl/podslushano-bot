import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { acceptRules, routeForError } from '@/api/community';
import { radius, useTheme } from '@/theme';
import { Button, PageScreen, Txt, useToast } from '@/ui';

const RULES: [string, string][] = [
  ['Уважайте друг друга', 'Без оскорблений, угроз, травли и дискриминации.'],
  ['Без мата и 18+', 'Пишите так, чтобы было не стыдно показать маме.'],
  ['Без политики', 'Мы здесь, чтобы помогать друг другу жить в Нидерландах.'],
  ['Без спама', 'Реклама бизнеса — через раздел «Для бизнеса».'],
  ['Чужие данные — нельзя', 'Адреса, телефоны, документы и фото без согласия не публикуем.'],
  ['Никакого мошенничества', 'И продажи запрещённого.'],
  ['Нарушения удаляем', 'Нарушителей блокируем. Недопустимый контент не терпим.'],
];

export default function Rules() {
  const { c } = useTheme();
  const { user } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const accept = async () => {
    if (!user) { router.push('/login'); return; }
    setBusy(true);
    try { await acceptRules(); toast('Спасибо! Добро пожаловать'); router.back(); }
    catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Ошибка', 'error'); }
    finally { setBusy(false); }
  };
  return (
    <PageScreen title="Правила" footer={<Button title="Принимаю правила" kind="primary" loading={busy} onPress={accept} />}>
      <View style={{ gap: 6 }}>
        <Txt v="overline" tone="accent">Сообщество podslushano</Txt>
        <Txt v="title1">Правила общения</Txt>
      </View>
      <View style={{ gap: 10 }}>
        {RULES.map(([h, t], i) => (
          <View key={h} style={{ flexDirection: 'row', gap: 14, backgroundColor: c.bgElevated, borderRadius: radius.l, padding: 16, borderWidth: 1, borderColor: c.line }}>
            <Txt v="title2" tone="accent" style={{ width: 22 }}>{i + 1}</Txt>
            <View style={{ flex: 1, gap: 2 }}>
              <Txt v="headline">{h}</Txt>
              <Txt v="callout" tone="muted">{t}</Txt>
            </View>
          </View>
        ))}
      </View>
      <Txt v="footnote">Увидели нарушение? Удерживайте сообщение — появится «Пожаловаться». Там же можно скрыть сообщения человека.</Txt>
    </PageScreen>
  );
}

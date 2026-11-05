import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { logout } from '@/api/auth';
import { api, ApiError } from '@/api/client';
import { radius, useTheme } from '@/theme';
import { Button, Field, PageScreen, Txt, useToast } from '@/ui';

const WORD = 'удалить';

/** Удаление аккаунта: что удалится, ввод слова для подтверждения, необратимое действие. */
export default function DeleteAccount() {
  const { c } = useTheme();
  const toast = useToast();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const ready = text.trim().toLowerCase() === WORD;

  const run = async () => {
    setBusy(true);
    try {
      await api('/api/app/me/delete', { confirm: true });
      await logout(false);
      toast('Аккаунт удалён');
      router.replace('/');
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Не получилось удалить аккаунт. Попробуйте ещё раз.', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <PageScreen title="Удаление аккаунта">
      <Txt v="title1" accessibilityRole="header">Удалить аккаунт?</Txt>
      <View style={{ backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: 1, borderColor: c.line, padding: 16, gap: 10 }}>
        <Txt v="headline">Что удалится</Txt>
        <Txt v="callout" tone="text">Имя, почта, телефон, фото, избранное, публикации, комментарии и объявления. Восстановить их будет нельзя.</Txt>
        <Txt v="headline">Что останется</Txt>
        <Txt v="callout" tone="text">Заказы из магазина: закон требует хранить их 7 лет, но они больше не будут связаны с аккаунтом. Записи о других оплатах — без личных данных.</Txt>
      </View>
      <Field label={`Чтобы подтвердить, напишите «${WORD}»`} value={text} onChangeText={setText} autoCapitalize="none" autoCorrect={false}
        accessibilityLabel="Слово для подтверждения удаления" />
      <Button kind="danger" icon="trash" title="Удалить аккаунт навсегда" disabled={!ready} loading={busy} onPress={run} />
      <Button kind="plain" title="Отмена" onPress={() => router.back()} />
    </PageScreen>
  );
}

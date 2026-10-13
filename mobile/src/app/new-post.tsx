import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';
import { useAuth } from '@/api/auth';
import { routeForError, sendPost } from '@/api/community';
import { queryClient } from '@/api/query';
import { Avatar, Button, Field, PageScreen, Txt, useToast } from '@/ui';

export default function NewPost() {
  const { user } = useAuth();
  const toast = useToast();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const publish = async () => {
    if (busy || !text.trim()) return;
    setBusy(true);
    try {
      await sendPost(text.trim());
      queryClient.invalidateQueries({ queryKey: ['posts'] });
      toast('Пост опубликован');
      router.back();
    } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не опубликовалось', 'error'); }
    finally { setBusy(false); }
  };
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen title="Новый пост" footer={<Button title="Опубликовать" kind="primary" loading={busy} disabled={!text.trim()} onPress={publish} />}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          {user ? <Avatar name={user.name} id={user.id} size={46} /> : null}
          <View style={{ flex: 1 }}>
            <Txt v="headline">{user?.name || 'Новый пост'}</Txt>
            <Txt v="footnote">Увидят все в ленте{user?.city ? ` · ${user.city}` : ''}</Txt>
          </View>
        </View>
        <Field value={text} onChangeText={setText} multiline multilineHeight={200} maxLength={2000} autoFocus
          placeholder="Вопрос, совет, находка или история" hint={`${text.length}/2000`} />
        <Txt v="footnote">Без мата, политики и рекламы — см. правила сообщества.</Txt>
      </PageScreen>
    </KeyboardAvoidingView>
  );
}

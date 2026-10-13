import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, Text, TextInput } from 'react-native';
import { Button, Eyebrow, H, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { useAuth } from '@/lib/auth';
import { routeForError, sendPost } from '@/lib/community';
import { notifyPostsChanged } from '@/lib/usePosts';

export default function NewPost() {
  const { user } = useAuth();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const publish = async () => {
    if (busy || !text.trim()) return;
    setBusy(true); setErr('');
    try { await sendPost(text.trim()); notifyPostsChanged(); router.back(); }
    catch (e: any) { if (!routeForError(e)) setErr(e?.message || 'Не опубликовалось'); }
    finally { setBusy(false); }
  };
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={{ padding: 20, gap: 14 }} keyboardShouldPersistTaps="handled">
        <Eyebrow>Лента</Eyebrow>
        <H size={24}>Новый пост</H>
        <P muted>Вопрос, совет, находка или история. Пост увидят все в ленте{user?.city ? `, с пометкой «${user.city}»` : ''}.</P>
        <TextInput value={text} onChangeText={setText} multiline maxLength={2000} placeholder="О чём хотите рассказать?"
          placeholderTextColor={C.muted} autoFocus
          style={{ minHeight: 160, backgroundColor: C.card, borderRadius: 18, borderWidth: 1, borderColor: C.line, padding: 14, fontSize: 16, color: C.ink, textAlignVertical: 'top' }} />
        <Text style={{ color: C.muted, alignSelf: 'flex-end' }}>{text.length}/2000</Text>
        <Button title={busy ? 'Публикуем…' : 'Опубликовать'} onPress={publish} disabled={busy || !text.trim()} />
        {err ? <Text style={{ color: C.warn }}>{err}</Text> : null}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

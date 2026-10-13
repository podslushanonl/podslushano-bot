import { Stack, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, KeyboardAvoidingView, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ActionSheet, SheetAction } from '@/components/ActionSheet';
import { Loading, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { useAuth } from '@/lib/auth';
import { Msg, block, messages, removeOwn, report, routeForError, sendMessage, timeLabel } from '@/lib/community';

const PAGE = 50; // столько последних сообщений сервер отдаёт без after/before
const POLL_MS = 4000;

export default function ChatRoom() {
  const { slug, title } = useLocalSearchParams<{ slug: string; title?: string }>();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();
  const [list, setList] = useState<Msg[] | null>(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [sheet, setSheet] = useState<Msg | null>(null);
  const listRef = useRef<FlatList<Msg>>(null);
  const last = useRef(0);

  const merge = (incoming: Msg[]) => {
    if (!incoming.length) return;
    last.current = Math.max(last.current, ...incoming.map((m) => m.id));
    setList((cur) => {
      const seen = new Set((cur || []).map((m) => m.id));
      return [...(cur || []), ...incoming.filter((m) => !seen.has(m.id))];
    });
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 50);
  };

  const polls = useRef(0);
  const poll = useCallback(async () => {
    try {
      // Каждый 5-й опрос (≈20 с) — полная сверка: так пропадают сообщения, скрытые модератором
      const full = !last.current || polls.current++ % 5 === 4;
      const d = await messages(String(slug), full ? undefined : last.current);
      if (full) {
        last.current = Math.max(last.current, 0, ...d.messages.map((m) => m.id));
        setList((cur) => {
          // Сервер отдаёт последние PAGE сообщений. Если пришло меньше — это все видимые,
          // старше окна ничего не осталось (в том числе когда пришёл пустой список)
          const oldest = d.messages.length >= PAGE ? d.messages[0].id : -Infinity;
          const keep = (cur || []).filter((m) => m.id < oldest); // старше загруженного окна не трогаем
          return [...keep, ...d.messages];
        });
      } else merge(d.messages);
    } catch { setList((cur) => cur || []); }
  }, [slug]);

  useEffect(() => {
    const first = setTimeout(poll, 0);
    const t = setInterval(poll, POLL_MS);
    return () => { clearTimeout(first); clearInterval(t); };
  }, [poll]);

  const send = async () => {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true); setErr('');
    try { merge([await sendMessage(String(slug), t)]); setText(''); }
    catch (e: any) { if (!routeForError(e)) setErr(e?.message || 'Не отправилось'); }
    finally { setBusy(false); }
  };

  const actions = (m: Msg): SheetAction[] => m.mine
    ? [{ title: 'Удалить сообщение', danger: true, onPress: () => removeOwn('msg', m.id).then(() => setList((c) => (c || []).filter((x) => x.id !== m.id))).catch(() => {}) }]
    : [
        { title: 'Пожаловаться', danger: true, onPress: () => report('msg', m.id).then(() => setErr('Спасибо, жалоба отправлена модераторам.')).catch((e) => { if (!routeForError(e)) setErr(e.message); }) },
        { title: `Скрыть сообщения: ${m.author.name}`, onPress: () => block(m.author.id).then(() => setList((c) => (c || []).filter((x) => x.author.id !== m.author.id))).catch((e) => { if (!routeForError(e)) setErr(e.message); }) },
      ];

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined} keyboardVerticalOffset={90}>
      <Stack.Screen options={{ title: title || 'Чат' }} />
      {list === null ? <Loading /> : (
        <FlatList
          ref={listRef}
          data={list}
          keyExtractor={(m) => String(m.id)}
          contentContainerStyle={{ padding: 12, gap: 8, flexGrow: 1 }}
          onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
          ListEmptyComponent={<View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}><P muted>Здесь пока тихо. Напишите первым!</P></View>}
          renderItem={({ item: m }) => (
            <Pressable onLongPress={() => user && setSheet(m)} delayLongPress={300}
              style={[s.bubble, m.mine ? s.mine : s.other]}>
              {!m.mine ? <Text style={s.name}>{m.author.name}{m.author.city ? ` · ${m.author.city}` : ''}</Text> : null}
              <Text style={[s.text, m.mine && { color: '#fff' }]}>{m.text}</Text>
              <Text style={[s.time, m.mine && { color: '#FFE2D4' }]}>{timeLabel(m.at)}</Text>
            </Pressable>
          )}
        />
      )}
      {err ? <Text style={s.err} onPress={() => setErr('')}>{err}</Text> : null}
      <View style={[s.bar, { paddingBottom: Math.max(insets.bottom, 10) }]}>
        <TextInput value={text} onChangeText={setText} placeholder={user ? 'Сообщение' : 'Войдите, чтобы писать'} placeholderTextColor={C.muted}
          style={s.input} multiline maxLength={1000} onFocus={() => { if (!user) routeForError({ status: 401 } as any); }} />
        <Pressable onPress={send} disabled={busy || !text.trim()} style={[s.send, (busy || !text.trim()) && { opacity: 0.4 }]}>
          <Text style={s.sendT}>↑</Text>
        </Pressable>
      </View>
      <ActionSheet visible={!!sheet} actions={sheet ? actions(sheet) : []} onClose={() => setSheet(null)} />
    </KeyboardAvoidingView>
  );
}

const s = StyleSheet.create({
  bubble: { maxWidth: '82%', borderRadius: 18, paddingHorizontal: 12, paddingVertical: 8, gap: 2 },
  mine: { alignSelf: 'flex-end', backgroundColor: C.accent, borderBottomRightRadius: 6 },
  other: { alignSelf: 'flex-start', backgroundColor: C.card, borderWidth: 1, borderColor: C.line, borderBottomLeftRadius: 6 },
  name: { fontSize: 12.5, fontWeight: '700', color: C.info },
  text: { fontSize: 15.5, lineHeight: 21, color: C.ink },
  time: { fontSize: 11, color: C.muted, alignSelf: 'flex-end' },
  bar: { flexDirection: 'row', alignItems: 'flex-end', gap: 8, paddingHorizontal: 10, paddingTop: 8, backgroundColor: C.card, borderTopWidth: 1, borderTopColor: C.line },
  input: { flex: 1, maxHeight: 120, minHeight: 42, backgroundColor: C.bg, borderRadius: 21, paddingHorizontal: 14, paddingVertical: 10, fontSize: 16, color: C.ink },
  send: { width: 42, height: 42, borderRadius: 21, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center' },
  sendT: { color: '#fff', fontSize: 22, fontWeight: '800' },
  err: { color: C.ink, backgroundColor: C.accentSoft, padding: 10, textAlign: 'center' },
});

import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { block, fetchMessages, Msg, removeOwn, report, routeForError, sendMessage } from '@/api/community';
import { joinRoom, onRealtime, realtimeConnected } from '@/api/dm';
import { Bubble, CHAT_HEADER_SPACE, ChatHeader, ChatShell, Composer } from '@/features/chat/ChatUI';
import { useTheme } from '@/theme';
import { ActionSheet, Empty, SheetAction, Skeleton, useToast } from '@/ui';

const PAGE = 50; // столько последних сообщений сервер отдаёт без after

export default function RoomScreen() {
  const { slug, title } = useLocalSearchParams<{ slug: string; title?: string }>();
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const toast = useToast();
  const [list, setList] = useState<Msg[] | null>(null);
  const [roomTitle, setRoomTitle] = useState(title || 'Чат');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [sheet, setSheet] = useState<Msg | null>(null);
  const fresh = useRef(new Set<number>());
  const last = useRef(0);

  const merge = useCallback((incoming: Msg[], mark = false) => {
    if (!incoming.length) return;
    last.current = Math.max(last.current, ...incoming.map((m) => m.id));
    if (mark) incoming.forEach((m) => fresh.current.add(m.id));
    setList((cur) => {
      const seen = new Set((cur || []).map((m) => m.id));
      return [...(cur || []), ...incoming.filter((m) => !seen.has(m.id))];
    });
  }, []);

  // Полная сверка: подтягивает пропущенное и убирает скрытое модератором
  const reconcile = useCallback(async () => {
    try {
      const d = await fetchMessages(String(slug));
      if (d.room?.title) setRoomTitle(d.room.title);
      last.current = Math.max(last.current, 0, ...d.messages.map((m) => m.id));
      setList((cur) => {
        const oldest = d.messages.length >= PAGE ? d.messages[0].id : -Infinity;
        return [...(cur || []).filter((m) => m.id < oldest), ...d.messages];
      });
    } catch { setList((cur) => cur || []); }
  }, [slug]);

  useEffect(() => {
    const t0 = setTimeout(reconcile, 0);
    const leave = joinRoom(String(slug));
    const off = onRealtime((e) => {
      if (e.type === 'room' && e.slug === slug) merge([{ ...e.message, mine: !!user && e.message.author.id === user.id }], true);
    });
    // Без живого соединения (не вошли / нет сети) — опрос; с ним — редкая сверка
    let ticks = 0;
    const t = setInterval(async () => {
      ticks++;
      if (realtimeConnected() && ticks % 6) return;
      if (ticks % 5 === 0 || !last.current) return reconcile();
      try { merge((await fetchMessages(String(slug), last.current)).messages, true); } catch { /* сеть */ }
    }, 5000);
    return () => { clearTimeout(t0); clearInterval(t); leave(); off(); };
  }, [slug, user, merge, reconcile]);

  const send = async () => {
    const t = text.trim();
    if (!t || busy) return;
    if (!user) { router.push('/login'); return; }
    setBusy(true);
    try { merge([await sendMessage(String(slug), t)], true); setText(''); }
    catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не отправилось', 'error'); }
    finally { setBusy(false); }
  };
  const fail = (e: any) => { if (!routeForError(e)) toast(e?.message || 'Ошибка', 'error'); };
  const actions = (m: Msg): SheetAction[] => m.mine
    ? [{ title: 'Удалить сообщение', icon: 'trash', danger: true, onPress: () => removeOwn('msg', m.id).then(() => setList((x) => (x || []).filter((y) => y.id !== m.id))).catch(fail) }]
    : [
        { title: 'Пожаловаться', icon: 'flag', danger: true, onPress: () => report('msg', m.id).then(() => toast('Жалоба отправлена модераторам')).catch(fail) },
        { title: `Скрыть сообщения: ${m.author.name}`, icon: 'block', onPress: () => block(m.author.id).then(() => setList((x) => (x || []).filter((y) => y.author.id !== m.author.id))).catch(fail) },
      ];
  const data = useMemo(() => [...(list || [])].reverse(), [list]);

  return (
    <ChatShell
      header={<ChatHeader title={roomTitle} sub="Городской чат · модерация включена" onBack={() => (router.canGoBack() ? router.back() : router.replace('/messages'))} />}
      composer={<Composer value={text} onChange={setText} onSend={send} busy={busy} placeholder={user ? 'Сообщение' : 'Войдите, чтобы писать'}
        onFocus={() => { if (!user) router.push('/login'); }} />}>
      {list === null ? (
        <View style={{ paddingTop: CHAT_HEADER_SPACE(insets.top, 12), paddingHorizontal: 14, gap: 10 }}>
          <Skeleton w="60%" h={54} r={20} /><Skeleton w="45%" h={44} r={20} style={{ alignSelf: 'flex-end' }} /><Skeleton w="70%" h={64} r={20} />
        </View>
      ) : (
        <FlatList
          inverted
          data={data}
          keyExtractor={(m) => String(m.id)}
          contentContainerStyle={{ paddingHorizontal: 12, paddingTop: 8, paddingBottom: CHAT_HEADER_SPACE(insets.top, 12), gap: 6, flexGrow: 1 }}
          ListEmptyComponent={<View style={{ transform: [{ scaleY: -1 }], flex: 1, justifyContent: 'center' }}>
            <Empty icon="bubble" title="Здесь пока тихо" text="Напишите первым — поздоровайтесь с соседями." /></View>}
          renderItem={({ item: m, index }) => {
            const prev = data[index + 1];
            const showName = !m.mine && (!prev || prev.author.id !== m.author.id);
            return (
              <View style={{ marginTop: prev && prev.author.id !== m.author.id ? 8 : 0 }}>
                <Bubble text={m.text} at={m.at} mine={m.mine} fresh={fresh.current.has(m.id)}
                  name={showName ? `${m.author.name}${m.author.city ? ` · ${m.author.city}` : ''}` : undefined}
                  onLongPress={() => (user ? setSheet(m) : router.push('/login'))} />
              </View>
            );
          }}
          style={{ backgroundColor: c.bg }}
        />
      )}
      <ActionSheet visible={!!sheet} actions={sheet ? actions(sheet) : []} onClose={() => setSheet(null)} />
    </ChatShell>
  );
}

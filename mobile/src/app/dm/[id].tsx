import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { routeForError } from '@/api/community';
import { DmMessage, markRead, onRealtime, reportDialog, sendDm, sendTyping, useDialog } from '@/api/dm';
import { photoUrl } from '@/api/market';
import { blockPerson } from '@/api/social';
import { queryClient } from '@/api/query';
import { Bubble, CHAT_HEADER_SPACE, ChatHeader, ChatShell, Composer } from '@/features/chat/ChatUI';
import { radius, useTheme } from '@/theme';
import { ActionSheet, Avatar, Button, Empty, IconButton, Img, Skeleton, Tap, Txt, useToast } from '@/ui';

export default function Dialog() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const conv = Number(id);
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const q = useDialog(conv);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [typing, setTyping] = useState(false);
  const [menu, setMenu] = useState(false);
  const fresh = useRef(new Set<number>());
  const typingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTyping = useRef(0);
  const cv = q.data?.conversation;
  const messages = useMemo(() => [...(q.data?.messages || [])].reverse(), [q.data]);
  const locked = cv?.can_write === false;   // писать можно только друзьям
  const openPeer = () => cv && router.push({ pathname: '/user/[id]', params: { id: String(cv.peer.id) } });

  useEffect(() => {
    const off = onRealtime((e) => {
      if (e.type === 'typing' && e.conv === conv) {
        setTyping(true);
        if (typingTimer.current) clearTimeout(typingTimer.current);
        typingTimer.current = setTimeout(() => setTyping(false), 4000);
      }
      if (e.type === 'dm' && e.conv === conv) {
        setTyping(false);
        fresh.current.add(e.message.id);
        if (!e.message.mine) markRead(conv).catch(() => {});
      }
    });
    return () => { off(); if (typingTimer.current) clearTimeout(typingTimer.current); };
  }, [conv]);

  // Открыли диалог — всё прочитано
  const unread = cv?.unread;
  useEffect(() => {
    if (!unread) return;
    markRead(conv).then(() => queryClient.invalidateQueries({ queryKey: ['me', 'dm'], exact: true })).catch(() => {});
  }, [conv, unread]);

  const change = (v: string) => {
    setText(v);
    if (Date.now() - lastTyping.current > 2500) { lastTyping.current = Date.now(); sendTyping(conv); }
  };
  const send = async () => {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    try {
      const m = await sendDm(conv, t);
      fresh.current.add(m.id);
      queryClient.setQueryData<{ conversation: any; messages: DmMessage[] }>(['me', 'dm', conv], (cur) =>
        cur && !cur.messages.some((x) => x.id === m.id) ? { ...cur, messages: [...cur.messages, m] } : cur);
      queryClient.invalidateQueries({ queryKey: ['me', 'dm'], exact: true });
      setText('');
    } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не отправилось', 'error'); }
    finally { setBusy(false); }
  };

  const back = () => (router.canGoBack() ? router.back() : router.replace('/messages'));
  return (
    <ChatShell
      header={
        <ChatHeader title={cv?.peer.name || 'Диалог'} sub={typing ? 'печатает…' : cv?.listing ? 'по объявлению' : undefined} onBack={back}
          left={cv ? <Tap onPress={openPeer} scaleTo={0.92} accessibilityLabel={`Профиль: ${cv.peer.name}`}><Avatar name={cv.peer.name} id={cv.peer.id} size={40} /></Tap> : null}
          right={cv ? <IconButton icon="more" label="Действия" kind="plain" onPress={() => setMenu(true)} /> : null}
          below={cv?.listing ? (
            <Tap onPress={() => router.push({ pathname: '/market/[id]', params: { id: String(cv.listing!.id) } })} scaleTo={0.98}
              style={{ flexDirection: 'row', alignItems: 'center', gap: 10, padding: 8, borderRadius: radius.m, backgroundColor: c.bgSunken }}>
              {cv.listing.photo ? <Img source={photoUrl(cv.listing)} style={{ width: 40, height: 40, borderRadius: 10 }} /> : null}
              <View style={{ flex: 1 }}>
                <Txt v="subhead" tone="ink" numberOfLines={1} style={{ fontFamily: 'Onest_600SemiBold' }}>{cv.listing.title}</Txt>
                {cv.listing.price ? <Txt v="footnote" tone="ink" style={{ fontFamily: 'Onest_700Bold' }}>{cv.listing.price}</Txt> : null}
              </View>
            </Tap>
          ) : null} />
      }
      composer={locked ? (
        <View style={{ paddingHorizontal: 14, paddingTop: 10, paddingBottom: Math.max(insets.bottom, 12), gap: 8, alignItems: 'center' }}>
          <Txt v="footnote" center>Писать в личные сообщения можно только друзьям.</Txt>
          <Button title={`Открыть профиль: ${cv!.peer.name}`} kind="secondary" size="s" full={false} icon="person" onPress={openPeer} />
        </View>
      ) : <Composer value={text} onChange={change} onSend={send} busy={busy} />}>
      {q.isLoading ? (
        <View style={{ paddingTop: CHAT_HEADER_SPACE(insets.top, 70), paddingHorizontal: 14, gap: 10 }}>
          <Skeleton w="60%" h={50} r={20} /><Skeleton w="45%" h={44} r={20} style={{ alignSelf: 'flex-end' }} />
        </View>
      ) : !cv ? (
        <View style={{ flex: 1, justifyContent: 'center' }}><Empty icon="bubble" title="Диалог недоступен" /></View>
      ) : (
        <FlatList
          inverted
          data={messages}
          keyExtractor={(m) => String(m.id)}
          contentContainerStyle={{ paddingHorizontal: 12, paddingTop: 8, paddingBottom: CHAT_HEADER_SPACE(insets.top, cv.listing ? 70 : 8), gap: 6, flexGrow: 1 }}
          ListEmptyComponent={<View style={{ transform: [{ scaleY: -1 }], flex: 1, justifyContent: 'center' }}>
            <Empty icon="bubble" title="Начните разговор" text={cv.listing ? 'Например: «Здравствуйте! Ещё актуально?»' : undefined} /></View>}
          renderItem={({ item: m }) => <Bubble text={m.text} at={m.at} mine={m.mine} read={m.mine ? m.read : undefined} fresh={fresh.current.has(m.id)} />}
          style={{ backgroundColor: c.bg }}
        />
      )}
      <ActionSheet visible={menu} onClose={() => setMenu(false)} actions={cv ? [
        { title: 'Пожаловаться', icon: 'flag', danger: true, onPress: () => reportDialog(conv).then(() => toast('Жалоба отправлена модераторам')).catch((e) => toast(e?.message || 'Ошибка', 'error')) },
        { title: `Профиль: ${cv.peer.name}`, icon: 'person', onPress: openPeer },
        { title: `Заблокировать: ${cv.peer.name}`, icon: 'block', onPress: () => blockPerson(cv.peer.id).then(() => { toast('Пользователь заблокирован'); back(); }).catch((e) => toast(e?.message || 'Ошибка', 'error')) },
      ] : []} />
    </ChatShell>
  );
}

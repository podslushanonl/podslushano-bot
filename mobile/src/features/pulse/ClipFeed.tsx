import { router, useIsFocused } from 'expo-router';
import { ReactNode, useCallback, useState } from 'react';
import { FlatList, KeyboardAvoidingView, Modal, Platform, Pressable, Share, useWindowDimensions, View, ViewToken } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { BOT } from '@/api/client';
import { removeOwn, report, routeForError } from '@/api/community';
import { addClipComment, Clip, PULSE_KEY, useClipComments } from '@/api/pulse';
import { queryClient } from '@/api/query';
import { Composer } from '@/features/chat/ChatUI';
import { timeLabel } from '@/features/feed/cards';
import { radius, useTheme } from '@/theme';
import { ActionSheet, Avatar, Skeleton, Txt, useToast, VerifiedBadge } from '@/ui';
import { ClipView } from './ClipView';

/** Комментарии к видео — лист снизу поверх ленты. */
function CommentsSheet({ clip, onClose }: { clip: Clip | null; onClose: () => void }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const toast = useToast();
  const q = useClipComments(clip?.id || 0);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const send = async () => {
    if (!clip || !text.trim() || busy) return;
    if (!user) { onClose(); router.push('/login'); return; }
    setBusy(true);
    try { await addClipComment(clip.id, text.trim()); setText(''); } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не отправилось', 'error'); }
    finally { setBusy(false); }
  };
  return (
    <Modal visible={!!clip} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={{ flex: 1, backgroundColor: c.scrim }} onPress={onClose} accessibilityLabel="Закрыть" />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ maxHeight: '72%', backgroundColor: c.bgElevated, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl }}>
        <View style={{ alignItems: 'center', paddingTop: 8 }}><View style={{ width: 36, height: 5, borderRadius: 3, backgroundColor: c.lineStrong }} /></View>
        <Txt v="headline" center style={{ paddingVertical: 10 }}>{clip?.comments ? `Комментарии · ${clip.comments}` : 'Комментарии'}</Txt>
        <FlatList data={q.data || []} keyExtractor={(x) => String(x.id)} style={{ flexGrow: 0 }}
          contentContainerStyle={{ paddingHorizontal: 16, gap: 14, paddingBottom: 8 }}
          ListEmptyComponent={q.isLoading ? <Skeleton h={48} /> : <Txt v="callout" tone="muted" center style={{ paddingVertical: 24 }}>Пока тихо. Напишите первым!</Txt>}
          renderItem={({ item: cm }) => (
            <View style={{ flexDirection: 'row', gap: 10 }}>
              <Avatar name={cm.author.name} id={cm.author.id} uri={cm.author.avatar} size={34} />
              <View style={{ flex: 1, gap: 2 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                  <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_700Bold' }}>{cm.author.name}</Txt>
                  {cm.author.verified ? <VerifiedBadge size={13} /> : null}
                  <Txt v="caption">{timeLabel(cm.at)}</Txt>
                </View>
                <Txt v="callout" tone="ink">{cm.text}</Txt>
              </View>
            </View>
          )} />
        <View style={{ paddingBottom: Math.max(insets.bottom - 10, 0) }}>
          <Composer value={text} onChange={setText} onSend={send} busy={busy} placeholder={user ? 'Комментарий' : 'Войдите, чтобы комментировать'} />
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

/** Лента вертикальных видео: ОДИН список во весь экран, листается строго по одному (pagingEnabled + snapToInterval).
 *  Используется во вкладке Pulse и при открытии видео человека из профиля. */
export function ClipFeed({ clips, bottom, initialIndex = 0, onEndReached, refreshing, onRefresh, overlay, empty }: {
  clips: Clip[]; bottom: number; initialIndex?: number; onEndReached?: () => void; refreshing?: boolean; onRefresh?: () => void;
  overlay?: ReactNode; empty?: ReactNode;
}) {
  const { width, height: winH } = useWindowDimensions();
  const { user } = useAuth();
  const toast = useToast();
  const focused = useIsFocused();
  const [height, setHeight] = useState(0);
  const [active, setActive] = useState(initialIndex);
  const [paused, setPaused] = useState(false);
  // В браузере видео со звуком само не запускается: начинаем без звука, включаем по тапу
  const [muted, setMuted] = useState(Platform.OS === 'web');
  const [comments, setComments] = useState<Clip | null>(null);
  const [menu, setMenu] = useState<Clip | null>(null);
  const h = height || winH;

  // Пролистали к другому видео — оно играет, пауза сбрасывается
  const onViewable = useCallback(({ viewableItems }: { viewableItems: ViewToken[] }) => {
    const first = viewableItems.find((v) => v.isViewable);
    if (first?.index != null) { setActive(first.index); setPaused(false); }
  }, []);
  const fail = (e: any) => { if (!routeForError(e)) toast(e?.message || 'Ошибка', 'error'); };
  const share = async (clip: Clip) => {
    const url = `${BOT}/app/pulse?clip=${clip.id}`;
    try {
      if (Platform.OS === 'web') {
        const nav = (globalThis as any).navigator;
        if (nav?.share) await nav.share({ title: 'podslushano.nl · Pulse', url }); else { await nav?.clipboard?.writeText(url); toast('Ссылка скопирована'); }
      } else await Share.share({ message: url });
    } catch { /* отменено */ }
  };

  return (
    <View style={{ flex: 1, backgroundColor: '#000000' }} onLayout={(e) => setHeight(e.nativeEvent.layout.height)}>
      {!clips.length ? empty : height ? (
        <FlatList
          data={clips}
          keyExtractor={(c) => String(c.id)}
          extraData={`${active}:${paused}:${muted}:${focused}`}
          renderItem={({ item, index }) => (
            <ClipView clip={item} active={focused && index === active} paused={paused} onTogglePause={() => setPaused(!paused)}
              width={width} height={h} bottom={bottom} muted={muted} onToggleMute={() => setMuted(!muted)} signedIn={!!user}
              onNeedLogin={() => router.push('/login')} onComments={() => setComments(item)} onShare={() => setMenu(item)} />
          )}
          pagingEnabled
          snapToInterval={h}
          snapToAlignment="start"
          decelerationRate="fast"
          disableIntervalMomentum
          showsVerticalScrollIndicator={false}
          initialScrollIndex={initialIndex || undefined}
          getItemLayout={(_, i) => ({ length: h, offset: h * i, index: i })}
          onViewableItemsChanged={onViewable}
          viewabilityConfig={{ itemVisiblePercentThreshold: 70 }}
          windowSize={3}
          initialNumToRender={2}
          maxToRenderPerBatch={2}
          removeClippedSubviews
          onEndReachedThreshold={2}
          onEndReached={onEndReached}
          refreshing={refreshing}
          onRefresh={onRefresh}
          style={{ flex: 1 }}
        />
      ) : null}
      {overlay}
      <CommentsSheet clip={comments ? clips.find((c) => c.id === comments.id) || comments : null} onClose={() => setComments(null)} />
      <ActionSheet visible={!!menu} onClose={() => setMenu(null)} actions={menu ? [
        { title: 'Поделиться ссылкой', icon: 'share', onPress: () => share(menu) },
        ...(menu.mine
          ? [{ title: 'Удалить видео', icon: 'trash' as const, danger: true, onPress: () => removeOwn('clip', menu.id)
              .then(() => queryClient.invalidateQueries({ queryKey: PULSE_KEY })).catch(fail) }]
          : [{ title: 'Пожаловаться', icon: 'flag' as const, danger: true, onPress: () => (user
              ? report('clip', menu.id).then(() => toast('Жалоба отправлена модераторам')).catch(fail) : router.push('/login')) }]),
      ] : []} />
    </View>
  );
}

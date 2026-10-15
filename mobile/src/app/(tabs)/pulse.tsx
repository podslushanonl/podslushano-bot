import { router, useIsFocused } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { FlatList, KeyboardAvoidingView, Modal, Platform, Pressable, TextInput, View, ViewToken } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { removeOwn, report, routeForError } from '@/api/community';
import { addClipComment, Clip, PULSE_KEY, uploadClip, useClipComments, usePulse } from '@/api/pulse';
import { queryClient } from '@/api/query';
import { Composer } from '@/features/chat/ChatUI';
import { timeLabel } from '@/features/feed/cards';
import { ClipView } from '@/features/pulse/ClipView';
import { pickMedia, PickedFile } from '@/lib/pickMedia';
import { radius, type as T, useTheme } from '@/theme';
import { ActionSheet, Avatar, Button, Empty, Glass, Icon, IconButton, Skeleton, TAB_SPACE, Txt, useToast, VerifiedBadge } from '@/ui';

/** Комментарии к видео — лист снизу поверх Pulse. */
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

/** Публикация видео в Pulse: превью выбранного файла и подпись. */
function UploadSheet({ file, onClose }: { file: PickedFile | null; onClose: () => void }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const publish = async () => {
    if (!file || busy) return;
    setBusy(true);
    try { await uploadClip(file, text.trim()); toast('Видео опубликовано'); setText(''); onClose(); }
    catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не загрузилось', 'error'); }
    finally { setBusy(false); }
  };
  return (
    <Modal visible={!!file} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={{ flex: 1, backgroundColor: c.scrim }} onPress={busy ? undefined : onClose} accessibilityLabel="Закрыть" />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ backgroundColor: c.bgElevated, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl, padding: 18, gap: 14,
          paddingBottom: insets.bottom + 18 }}>
        <Txt v="title3">Новое видео в Pulse</Txt>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, padding: 12, borderRadius: radius.m, backgroundColor: c.bgSunken }}>
          <Icon name="pulse" size={22} color={c.accent} />
          <Txt v="subhead" tone="ink" numberOfLines={1} style={{ flex: 1 }}>{file?.name}</Txt>
        </View>
        <TextInput value={text} onChangeText={setText} placeholder="Подпись к видео" placeholderTextColor={c.faint} multiline maxLength={500}
          accessibilityLabel="Подпись к видео" style={[T.body, { color: c.ink, minHeight: 60, outlineStyle: 'none' } as any]} />
        <Button title="Опубликовать" kind="accent" loading={busy} onPress={publish} />
        <Txt v="footnote" tone="muted" center>Вертикальное видео до 60 секунд и 80 МБ. Без мата, политики и рекламы.</Txt>
      </KeyboardAvoidingView>
    </Modal>
  );
}

/** Pulse — вертикальные видео во весь экран: листаются по одному, играет то, что на экране. */
export default function Pulse() {
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const toast = useToast();
  const q = usePulse();
  // Ушли на другую вкладку — видео на паузе (экран вкладки остаётся загруженным)
  const focused = useIsFocused();
  const clips = useMemo(() => q.data?.pages.flatMap((p) => p.clips) || [], [q.data]);
  const [height, setHeight] = useState(0);
  const [active, setActive] = useState(0);
  // В браузере видео со звуком само не запускается: начинаем без звука, включаем по тапу
  const [muted, setMuted] = useState(Platform.OS === 'web');
  const [comments, setComments] = useState<Clip | null>(null);
  const [menu, setMenu] = useState<Clip | null>(null);
  const [file, setFile] = useState<PickedFile | null>(null);
  const [paused, setPaused] = useState(false);
  // Пролистали к другому видео — оно играет, пауза сбрасывается
  const onViewable = useCallback(({ viewableItems }: { viewableItems: ViewToken[] }) => {
    const first = viewableItems.find((v) => v.isViewable);
    if (first?.index != null) { setActive(first.index); setPaused(false); }
  }, []);
  const bottom = (Platform.OS === 'web' ? TAB_SPACE : 0) + 8;

  const add = useCallback(async () => {
    if (!user) { router.push('/login'); return; }
    const f = await pickMedia(['videos']);
    if (f && f.kind !== 'video') { toast('Выберите видео', 'error'); return; }
    if (f) setFile(f);
  }, [user, toast]);
  const fail = (e: any) => { if (!routeForError(e)) toast(e?.message || 'Ошибка', 'error'); };

  return (
    <View style={{ flex: 1, backgroundColor: '#000000' }} onLayout={(e) => setHeight(e.nativeEvent.layout.height)}>
      {height ? (
        q.isLoading ? <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}><Skeleton w={60} h={60} r={30} /></View>
        : clips.length ? (
          <FlatList
            data={clips}
            keyExtractor={(c) => String(c.id)}
            extraData={`${active}:${paused}:${muted}:${focused}`}
            renderItem={({ item, index }) => (
              <ClipView clip={item} active={focused && index === active} paused={paused} onTogglePause={() => setPaused(!paused)} height={height} bottom={bottom} muted={muted} onToggleMute={() => setMuted(!muted)}
                signedIn={!!user} onNeedLogin={() => router.push('/login')} onComments={() => setComments(item)} onMenu={() => setMenu(item)} />
            )}
            pagingEnabled
            snapToInterval={height}
            snapToAlignment="start"
            decelerationRate="fast"
            showsVerticalScrollIndicator={false}
            getItemLayout={(_, i) => ({ length: height, offset: height * i, index: i })}
            onViewableItemsChanged={onViewable}
            viewabilityConfig={{ itemVisiblePercentThreshold: 70 }}
            windowSize={3}
            initialNumToRender={2}
            maxToRenderPerBatch={2}
            removeClippedSubviews
            onEndReachedThreshold={2}
            onEndReached={() => { if (q.hasNextPage && !q.isFetchingNextPage) q.fetchNextPage(); }}
            refreshing={q.isRefetching}
            onRefresh={() => { queryClient.resetQueries({ queryKey: PULSE_KEY, exact: true }); setActive(0); }}
          />
        ) : (
          <View style={{ flex: 1, justifyContent: 'center', paddingHorizontal: 20 }}>
            <Glass radius={radius.xl} strong>
              <Empty icon="pulse" title="Здесь будут вертикальные видео" text="Снимите, что происходит вокруг: город, события, находки. Первое видео — ваше?"
                action={<Button title="Загрузить видео" kind="accent" icon="plus" onPress={add} />} />
            </Glass>
          </View>
        )
      ) : null}

      <View pointerEvents="box-none" style={{ position: 'absolute', top: insets.top + 8, left: 16, right: 12, flexDirection: 'row', alignItems: 'center' }}>
        <Txt v="title2" color="#FFFFFF" style={{ flex: 1, fontFamily: 'Unbounded_700Bold', textShadowColor: 'rgba(0,0,0,0.5)', textShadowRadius: 6 }}>Pulse</Txt>
        <IconButton icon={muted ? 'volumeOff' : 'volumeOn'} label={muted ? 'Включить звук' : 'Выключить звук'} kind="plain" color="#FFFFFF" onPress={() => setMuted(!muted)} />
        <IconButton icon="plus" label="Загрузить видео" kind="plain" color="#FFFFFF" onPress={add} />
      </View>

      <CommentsSheet clip={comments ? clips.find((c) => c.id === comments.id) || comments : null} onClose={() => setComments(null)} />
      <UploadSheet file={file} onClose={() => setFile(null)} />
      <ActionSheet visible={!!menu} onClose={() => setMenu(null)} actions={menu ? (menu.mine
        ? [{ title: 'Удалить видео', icon: 'trash', danger: true, onPress: () => removeOwn('clip', menu.id).then(() => queryClient.invalidateQueries({ queryKey: PULSE_KEY, exact: true })).catch(fail) }]
        : [{ title: 'Пожаловаться', icon: 'flag', danger: true, onPress: () => (user ? report('clip', menu.id).then(() => toast('Жалоба отправлена модераторам')).catch(fail) : router.push('/login')) }]) : []} />
    </View>
  );
}

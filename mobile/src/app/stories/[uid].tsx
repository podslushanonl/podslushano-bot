import { useEventListener } from 'expo';
import { router, useLocalSearchParams } from 'expo-router';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, useWindowDimensions, View } from 'react-native';
import Animated, { cancelAnimation, Easing, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { scheduleOnRN } from 'react-native-worklets';
import { useAuth } from '@/api/auth';
import { mediaUrl } from '@/api/client';
import { routeForError } from '@/api/community';
import { deleteStory, reactStory, StoryItem, useStories } from '@/api/stories';
import { timeLabel } from '@/features/feed/cards';
import { seenStories } from '@/features/stories/seen';
import { Avatar, IconButton, Img, Tap, Txt, useToast, VerifiedBadge } from '@/ui';

const PHOTO_MS = 5000;

/** Видео истории: играет сразу, по окончании — следующая история; полоска прогресса идёт по времени видео. */
function StoryVideo({ url, onEnd, onProgress, paused }: { url: string; onEnd: () => void; onProgress: (p: number) => void; paused: boolean }) {
  const player = useVideoPlayer(mediaUrl(url), (p) => { p.loop = false; p.muted = false; p.timeUpdateEventInterval = 0.1; p.play(); });
  useEventListener(player, 'playToEnd', onEnd);
  useEventListener(player, 'timeUpdate', ({ currentTime }) => { if (player.duration) onProgress(currentTime / player.duration); });
  useEffect(() => { if (paused) player.pause(); else player.play(); }, [paused, player]);
  return <VideoView player={player} contentFit="cover" nativeControls={false} style={{ width: '100%', height: '100%' }} />;
}

/** Просмотр историй во весь экран (9:16): полоски прогресса, тап слева/справа — назад/вперёд, внизу — быстрые реакции. */
export default function StoryViewer() {
  const { uid } = useLocalSearchParams<{ uid: string }>();
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const toast = useToast();
  const q = useStories(!!user);
  const groups = useMemo(() => q.data?.groups || [], [q.data]);
  const reactions = q.data?.reactions || [];
  const [g, setG] = useState(() => Math.max(0, groups.findIndex((x) => String(x.user.id) === uid)));
  const [i, setI] = useState(0);
  const [held, setHeld] = useState(false);
  const progress = useSharedValue(0);
  const group = groups[g];
  const story: StoryItem | undefined = group?.items[i];
  const close = () => (router.canGoBack() ? router.back() : router.replace('/'));

  const next = () => {
    if (!group) return close();
    if (i < group.items.length - 1) setI(i + 1);
    else if (g < groups.length - 1) { setG(g + 1); setI(0); }
    else close();
  };
  const prev = () => {
    if (i > 0) setI(i - 1);
    else if (g > 0) { setG(g - 1); setI(Math.max(0, groups[g - 1].items.length - 1)); }
  };

  // Фото — 5 секунд; удержание пальцем ставит на паузу
  useEffect(() => {
    if (!story) return;
    seenStories.add(story.id);
    progress.set(0);
    if (story.kind !== 'photo' || held) return;
    progress.set(withTiming(1, { duration: PHOTO_MS, easing: Easing.linear }, (done) => { if (done) scheduleOnRN(next); }));
    return () => cancelAnimation(progress);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [story?.id, held]);

  const bar = useAnimatedStyle(() => ({ width: `${progress.get() * 100}%` }));
  if (!group || !story) {
    return <View style={{ flex: 1, backgroundColor: '#000000' }}><View style={{ marginTop: insets.top + 8, marginLeft: 8 }}><IconButton icon="close" label="Закрыть" kind="plain" color="#FFFFFF" onPress={close} /></View></View>;
  }
  // Кадр 9:16 по центру экрана (на широком экране — с чёрными полями)
  const frameW = Math.min(width, (height - insets.top - insets.bottom) * 9 / 16);
  const react = (emoji: string) => reactStory(story.id, emoji).then(() => toast(`Реакция ${emoji} отправлена`)).catch((e) => { if (!routeForError(e)) toast(e?.message || 'Ошибка', 'error'); });

  return (
    <View style={{ flex: 1, backgroundColor: '#000000', alignItems: 'center', paddingTop: insets.top, paddingBottom: insets.bottom }}>
      <View style={{ width: frameW, aspectRatio: 9 / 16, maxHeight: '100%', borderRadius: 14, overflow: 'hidden', backgroundColor: '#111111' }}>
        {story.kind === 'video'
          ? <StoryVideo key={story.id} url={story.url} paused={held} onEnd={next} onProgress={(p) => progress.set(p)} />
          : <Img source={mediaUrl(story.url)} style={{ width: '100%', height: '100%', backgroundColor: '#111111' }} />}

        {/* Тап слева — назад, справа — вперёд; удержание — пауза */}
        <View style={{ position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, flexDirection: 'row' }}>
          <Pressable style={{ flex: 1 }} onPress={prev} onLongPress={() => setHeld(true)} onPressOut={() => setHeld(false)} accessibilityLabel="Предыдущая история" />
          <Pressable style={{ flex: 2 }} onPress={next} onLongPress={() => setHeld(true)} onPressOut={() => setHeld(false)} accessibilityLabel="Следующая история" />
        </View>

        <View pointerEvents="box-none" style={{ position: 'absolute', top: 8, left: 8, right: 8, gap: 10 }}>
          <View style={{ flexDirection: 'row', gap: 4 }}>
            {group.items.map((s, k) => (
              <View key={s.id} style={{ flex: 1, height: 2.5, borderRadius: 2, backgroundColor: 'rgba(255,255,255,0.35)', overflow: 'hidden' }}>
                {k < i ? <View style={{ flex: 1, backgroundColor: '#FFFFFF' }} /> : k === i ? <Animated.View style={[{ height: '100%', backgroundColor: '#FFFFFF' }, bar]} /> : null}
              </View>
            ))}
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
            <Tap onPress={() => router.push({ pathname: '/user/[id]', params: { id: String(group.user.id) } })} scaleTo={0.95}
              style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8 }} accessibilityLabel={`Профиль: ${group.user.name}`}>
              <Avatar name={group.user.name} id={group.user.id} uri={group.user.avatar} size={34} />
              <Txt v="subhead" color="#FFFFFF" style={{ fontFamily: 'Onest_700Bold', flexShrink: 1 }} numberOfLines={1}>{group.mine ? 'Ваша история' : group.user.name}</Txt>
              {group.user.verified ? <VerifiedBadge size={14} /> : null}
              <Txt v="caption" color="rgba(255,255,255,0.7)">{timeLabel(story.at)}</Txt>
            </Tap>
            {group.mine ? <IconButton icon="trash" label="Удалить историю" kind="plain" color="#FFFFFF"
              onPress={() => deleteStory(story.id).then(() => { toast('История удалена'); close(); }).catch(() => {})} /> : null}
            <IconButton icon="close" label="Закрыть" kind="plain" color="#FFFFFF" onPress={close} />
          </View>
        </View>
      </View>

      {/* Быстрые реакции — нижняя панель, как в Instagram */}
      {!group.mine ? (
        <View style={{ flexDirection: 'row', justifyContent: 'center', gap: 6, paddingVertical: 10, width: frameW }}>
          {reactions.map((e) => {
            const on = story.my_reaction === e;
            return (
              <Tap key={e} onPress={() => react(e)} scaleTo={0.8} haptic="light" accessibilityLabel={`Реакция ${e}`} accessibilityState={{ selected: on }}
                style={{ width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center',
                  backgroundColor: on ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.08)', borderWidth: on ? 1 : 0, borderColor: 'rgba(255,255,255,0.6)' }}>
                <Txt v="title3" style={{ fontSize: 26, lineHeight: 32 }}>{e}</Txt>
              </Tap>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

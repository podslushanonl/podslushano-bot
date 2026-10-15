import { useEvent, useEventListener } from 'expo';
import { router } from 'expo-router';
import { useVideoPlayer, VideoPlayer, VideoView } from 'expo-video';
import { ReactNode, useEffect, useRef, useState } from 'react';
import { Platform, Pressable, View, ViewStyle } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withSequence, withSpring, withTiming } from 'react-native-reanimated';
import { mediaUrl } from '@/api/client';
import { Clip, toggleClip } from '@/api/pulse';
import { Avatar, Icon, IconName, Tap, Txt, VerifiedBadge } from '@/ui';

// Звук и частоту событий меняем у самого плеера (объект expo-video), а не через состояние React
const setMuted = (p: VideoPlayer, v: boolean) => { p.muted = v; };
const setupPlayer = (p: VideoPlayer, muted: boolean) => { p.loop = true; p.muted = muted; p.timeUpdateEventInterval = 0.25; };

const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1).replace('.', ',')}K` : String(n));
// Тень у белых иконок и текста поверх любого видео (как в TikTok и Reels)
const SHADOW: ViewStyle = Platform.OS === 'web'
  ? ({ filter: 'drop-shadow(0 1px 3px rgba(0,0,0,0.55))' } as any)
  : { shadowColor: '#000000', shadowOpacity: 0.5, shadowRadius: 3, shadowOffset: { width: 0, height: 1 } };
const TEXT_SHADOW = { textShadowColor: 'rgba(0,0,0,0.55)', textShadowRadius: 4, textShadowOffset: { width: 0, height: 1 } };
const FILL = { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 } as const;

/** Кнопка правой колонки: белая иконка без подложки, с тенью, счётчик под ней. */
function Side({ icon, label, count, color = '#FFFFFF', onPress, children }: {
  icon?: IconName; label: string; count?: string; color?: string; onPress: () => void; children?: ReactNode;
}) {
  return (
    <Tap onPress={onPress} scaleTo={0.82} haptic="light" accessibilityLabel={label} style={{ alignItems: 'center', gap: 3, minWidth: 48 }}>
      <View style={SHADOW}>{children ?? <Icon name={icon!} filled size={33} color={color} />}</View>
      {count ? <Txt v="caption" color="#FFFFFF" style={{ fontFamily: 'Onest_600SemiBold', fontSize: 12.5, ...TEXT_SHADOW }}>{count}</Txt> : null}
    </Tap>
  );
}

/** Одно видео Pulse на весь экран. Тап — пауза, двойной тап — лайк с сердцем, справа — действия, снизу — автор и подпись. */
export function ClipView({ clip, active, paused, onTogglePause, height, width, bottom, muted, onToggleMute, onComments, onShare, onNeedLogin, signedIn }: {
  clip: Clip; active: boolean; paused: boolean; onTogglePause: () => void; height: number; width: number; bottom: number;
  muted: boolean; onToggleMute: () => void; onComments: () => void; onShare: () => void; onNeedLogin: () => void; signedIn: boolean;
}) {
  const player = useVideoPlayer(mediaUrl(clip.url), (p) => setupPlayer(p, muted));
  const { isPlaying } = useEvent(player, 'playingChange', { isPlaying: player.playing });
  const progress = useSharedValue(0);
  const heart = useSharedValue(0);
  const lastTap = useRef(0);
  const single = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [more, setMore] = useState(false);

  useEventListener(player, 'timeUpdate', ({ currentTime }) => { if (player.duration) progress.set(currentTime / player.duration); });
  useEffect(() => { setMuted(player, muted); }, [player, muted]);
  useEffect(() => {
    if (active && !paused) player.play(); else player.pause();
  }, [active, paused, player]);
  useEffect(() => () => { if (single.current) clearTimeout(single.current); }, []);

  const like = (on?: boolean) => {
    if (!signedIn) { onNeedLogin(); return; }
    if (on && clip.liked) return;
    toggleClip(clip, 'like').catch(() => {});
  };
  const save = () => (signedIn ? toggleClip(clip, 'save').catch(() => {}) : onNeedLogin());
  // Одинарный тап ждёт: вдруг это двойной (лайк)
  const tap = () => {
    const now = Date.now();
    if (now - lastTap.current < 280) {
      lastTap.current = 0;
      if (single.current) clearTimeout(single.current);
      heart.set(withSequence(withSpring(1, { damping: 9, stiffness: 260 }), withTiming(1, { duration: 380 }), withTiming(0, { duration: 220 })));
      like(true);
      return;
    }
    lastTap.current = now;
    single.current = setTimeout(() => (muted ? onToggleMute() : onTogglePause()), 280);
  };

  const bar = useAnimatedStyle(() => ({ width: `${progress.get() * 100}%` }));
  const pop = useAnimatedStyle(() => ({ opacity: heart.get(), transform: [{ scale: 0.6 + heart.get() * 0.6 }, { rotate: '-8deg' }] }));

  return (
    <View style={{ width, height, backgroundColor: '#000000', overflow: 'hidden' }}>
      {/* playsInline: в Safari на iPhone видео играет прямо в ленте, а не открывается отдельным плеером */}
      <VideoView player={player} contentFit="cover" nativeControls={false} playsInline allowsPictureInPicture={false} style={FILL} />
      <Pressable onPress={tap} accessibilityLabel={paused ? 'Продолжить' : 'Пауза. Двойной тап — нравится'} style={FILL} />

      {paused || (active && !isPlaying && !muted) ? (
        <View pointerEvents="none" style={{ position: 'absolute', top: height / 2 - 36, alignSelf: 'center', opacity: 0.85, ...SHADOW }}>
          <Icon name="play" size={64} color="#FFFFFF" />
        </View>
      ) : null}
      <Animated.View pointerEvents="none" style={[{ position: 'absolute', top: height / 2 - 60, alignSelf: 'center' }, pop]}>
        <Icon name="heartFill" filled size={120} color="#FF3B5C" />
      </Animated.View>

      {/* Затемнение снизу — подпись читается на любом видео */}
      <View pointerEvents="none" style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 280,
        [Platform.OS === 'web' ? 'backgroundImage' : 'experimental_backgroundImage']: 'linear-gradient(to top, rgba(0,0,0,0.6), rgba(0,0,0,0))' } as any} />

      <View style={{ position: 'absolute', right: 8, bottom: bottom + 18, alignItems: 'center', gap: 20 }}>
        <Side label={clip.liked ? 'Убрать лайк' : 'Нравится'} icon="heartFill" color={clip.liked ? '#FF3B5C' : '#FFFFFF'}
          count={fmt(clip.likes)} onPress={() => like()} />
        <Side label="Комментарии" icon="bubbleFill" count={fmt(clip.comments)} onPress={onComments} />
        <Side label={clip.saved ? 'Убрать из закладок' : 'В закладки'} icon="bookmarkFill" color={clip.saved ? '#FFC93C' : '#FFFFFF'}
          count={clip.saved ? 'Сохр.' : ''} onPress={save} />
        <Side label="Поделиться" icon="paperplane" onPress={onShare} />
      </View>

      <View pointerEvents="box-none" style={{ position: 'absolute', left: 14, right: 80, bottom: bottom + 18, gap: 8 }}>
        <Tap onPress={() => router.push({ pathname: '/user/[id]', params: { id: String(clip.author.id) } })} scaleTo={0.96}
          accessibilityLabel={`Профиль: ${clip.author.name}`} style={{ flexDirection: 'row', alignItems: 'center', gap: 9, alignSelf: 'flex-start' }}>
          <View style={{ borderWidth: 1.5, borderColor: '#FFFFFF', borderRadius: 18 }}>
            <Avatar name={clip.author.name} id={clip.author.id} uri={clip.author.avatar} size={32} />
          </View>
          <Txt v="bodyStrong" color="#FFFFFF" numberOfLines={1} style={{ flexShrink: 1, ...TEXT_SHADOW }}>{clip.author.name}</Txt>
          {clip.author.verified ? <VerifiedBadge size={15} /> : null}
          {clip.author.city ? <Txt v="footnote" color="rgba(255,255,255,0.8)" style={TEXT_SHADOW}>· {clip.author.city}</Txt> : null}
        </Tap>
        {clip.text ? (
          <Pressable onPress={() => setMore(!more)} accessibilityLabel={more ? 'Свернуть подпись' : 'Показать подпись полностью'}>
            <Txt v="callout" color="#FFFFFF" numberOfLines={more ? 8 : 2} style={TEXT_SHADOW}>{clip.text}</Txt>
          </Pressable>
        ) : null}
      </View>

      {muted ? (
        <Tap onPress={onToggleMute} scaleTo={0.9} accessibilityLabel="Включить звук"
          style={{ position: 'absolute', right: 14, top: 0, marginTop: 64, width: 36, height: 36, borderRadius: 18, alignItems: 'center',
            justifyContent: 'center', backgroundColor: 'rgba(0,0,0,0.35)' }}>
          <Icon name="volumeOff" size={17} color="#FFFFFF" />
        </Tap>
      ) : null}

      {/* Тонкая полоска прогресса у нижнего края */}
      <View pointerEvents="none" style={{ position: 'absolute', left: 0, right: 0, bottom, height: 2, backgroundColor: 'rgba(255,255,255,0.2)' }}>
        <Animated.View style={[{ height: 2, backgroundColor: '#FFFFFF' }, bar]} />
      </View>
    </View>
  );
}

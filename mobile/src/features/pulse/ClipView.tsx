import { router } from 'expo-router';
import { useEvent } from 'expo';
import { useVideoPlayer, VideoPlayer, VideoView } from 'expo-video';
import { useEffect } from 'react';
import { Platform, Pressable, Share, View } from 'react-native';
import { BOT, mediaUrl } from '@/api/client';
import { Clip, toggleClip } from '@/api/pulse';
import { Avatar, Icon, IconName, Tap, Txt, VerifiedBadge } from '@/ui';

// Звук меняем у самого плеера (объект expo-video), а не через состояние React
const setMuted = (p: VideoPlayer, v: boolean) => { p.muted = v; };

const fmt = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1).replace('.', ',')} тыс.` : String(n));

/** Кнопка правой панели Pulse: иконка с тенью и подпись-счётчик под ней. */
function SideButton({ icon, label, count, color = '#FFFFFF', onPress }: { icon: IconName; label: string; count?: string; color?: string; onPress: () => void }) {
  return (
    <Tap onPress={onPress} scaleTo={0.86} haptic="light" accessibilityLabel={label} style={{ alignItems: 'center', gap: 4 }}>
      <View style={{ width: 48, height: 48, borderRadius: 24, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0,0,0,0.28)' }}>
        <Icon name={icon} filled size={28} color={color} />
      </View>
      {count !== undefined ? <Txt v="caption" color="#FFFFFF" style={{ fontFamily: 'Onest_700Bold', textShadowColor: 'rgba(0,0,0,0.6)', textShadowRadius: 4 }}>{count}</Txt> : null}
    </Tap>
  );
}

/** Одно видео Pulse во весь экран: играет, когда на экране; справа — лайк, комментарии, поделиться, закладки. */
export function ClipView({ clip, active, paused, onTogglePause, height, bottom, muted, onToggleMute, onComments, onMenu, onNeedLogin, signedIn }: {
  clip: Clip; active: boolean; paused: boolean; onTogglePause: () => void; height: number; bottom: number; muted: boolean; onToggleMute: () => void;
  onComments: () => void; onMenu: () => void; onNeedLogin: () => void; signedIn: boolean;
}) {
  const player = useVideoPlayer(mediaUrl(clip.url), (p) => { p.loop = true; p.muted = muted; });
  const { isPlaying } = useEvent(player, 'playingChange', { isPlaying: player.playing });

  useEffect(() => { setMuted(player, muted); }, [player, muted]);
  useEffect(() => {
    if (active && !paused) player.play(); else player.pause();
  }, [active, paused, player]);

  const act = (what: 'like' | 'save') => (signedIn ? toggleClip(clip, what).catch(() => {}) : onNeedLogin());
  const share = async () => {
    const url = `${BOT}/app/pulse?clip=${clip.id}`;
    try {
      if (Platform.OS === 'web') {
        const nav = (globalThis as any).navigator;
        if (nav?.share) await nav.share({ title: 'podslushano.nl · Pulse', url }); else await nav?.clipboard?.writeText(url);
      } else await Share.share({ message: url });
    } catch { /* отменено */ }
  };

  return (
    <View style={{ height, backgroundColor: '#000000' }}>
      <VideoView player={player} contentFit="cover" nativeControls={false} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }} />
      {/* Тап по видео — пауза / продолжить; при выключенном звуке — сначала включить звук */}
      <Pressable accessibilityLabel={paused ? 'Продолжить' : 'Пауза'} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }}
        onPress={() => (muted ? onToggleMute() : onTogglePause())} />
      {paused || (active && !isPlaying && !muted) ? (
        <View pointerEvents="none" style={{ position: 'absolute', top: '45%', alignSelf: 'center', width: 72, height: 72, borderRadius: 36,
          backgroundColor: 'rgba(0,0,0,0.35)', alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="play" size={34} color="#FFFFFF" />
        </View>
      ) : null}
      {muted ? (
        <Tap onPress={onToggleMute} scaleTo={0.9} accessibilityLabel="Включить звук"
          style={{ position: 'absolute', top: '45%', alignSelf: 'center', flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 16, height: 40,
            borderRadius: 20, backgroundColor: 'rgba(0,0,0,0.45)' }}>
          <Icon name="volumeOff" size={18} color="#FFFFFF" />
          <Txt v="subhead" color="#FFFFFF" style={{ fontFamily: 'Onest_600SemiBold' }}>Включить звук</Txt>
        </Tap>
      ) : null}

      {/* Затемнение снизу, чтобы подпись читалась на любом видео */}
      <View pointerEvents="none" style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 260,
        [Platform.OS === 'web' ? 'backgroundImage' : 'experimental_backgroundImage']: 'linear-gradient(to top, rgba(0,0,0,0.65), rgba(0,0,0,0))' } as any} />

      <View style={{ position: 'absolute', right: 10, bottom: bottom + 16, alignItems: 'center', gap: 16 }}>
        <Tap onPress={() => router.push({ pathname: '/user/[id]', params: { id: String(clip.author.id) } })} scaleTo={0.9}
          accessibilityLabel={`Профиль: ${clip.author.name}`}>
          <View style={{ borderWidth: 2, borderColor: '#FFFFFF', borderRadius: 26 }}>
            <Avatar name={clip.author.name} id={clip.author.id} uri={clip.author.avatar} size={46} />
          </View>
        </Tap>
        <SideButton icon={clip.liked ? 'heartFill' : 'heart'} color={clip.liked ? '#FF3B5C' : '#FFFFFF'} label={clip.liked ? 'Убрать лайк' : 'Нравится'}
          count={fmt(clip.likes)} onPress={() => act('like')} />
        <SideButton icon="bubble" label="Комментарии" count={fmt(clip.comments)} onPress={onComments} />
        <SideButton icon="share" label="Поделиться" count="" onPress={share} />
        <SideButton icon={clip.saved ? 'bookmarkFill' : 'bookmark'} color={clip.saved ? '#FFC93C' : '#FFFFFF'}
          label={clip.saved ? 'Убрать из закладок' : 'В закладки'} count="" onPress={() => act('save')} />
        <SideButton icon="more" label="Ещё" onPress={onMenu} />
      </View>

      <View pointerEvents="box-none" style={{ position: 'absolute', left: 14, right: 84, bottom: bottom + 18, gap: 6 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Txt v="bodyStrong" color="#FFFFFF" numberOfLines={1} style={{ flexShrink: 1, textShadowColor: 'rgba(0,0,0,0.5)', textShadowRadius: 4 }}>
            {clip.author.name}
          </Txt>
          {clip.author.verified ? <VerifiedBadge size={15} /> : null}
          {clip.author.city ? <Txt v="footnote" color="rgba(255,255,255,0.75)" style={{ marginLeft: 6 }}>· {clip.author.city}</Txt> : null}
        </View>
        {clip.text ? <Txt v="callout" color="#FFFFFF" numberOfLines={3} style={{ textShadowColor: 'rgba(0,0,0,0.5)', textShadowRadius: 4 }}>{clip.text}</Txt> : null}
      </View>
    </View>
  );
}

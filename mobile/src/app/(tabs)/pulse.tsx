import { router } from 'expo-router';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useCallback, useMemo, useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Modal, Platform, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { PULSE_KEY, uploadClip, usePulse } from '@/api/pulse';
import { queryClient } from '@/api/query';
import { ClipFeed } from '@/features/pulse/ClipFeed';
import { pickMedia, PickedFile } from '@/lib/pickMedia';
import { radius, type as T, useTheme } from '@/theme';
import { Button, Icon, IconButton, Tap, Txt, useToast } from '@/ui';

const SHADOW = { textShadowColor: 'rgba(0,0,0,0.5)', textShadowRadius: 6 };

/** Публикация видео: превью во весь экран, подпись поверх и кнопка «Опубликовать» внизу — как в Reels. */
function UploadScreen({ file, onClose }: { file: PickedFile; onClose: () => void }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const player = useVideoPlayer(file.uri, (p) => { p.loop = true; p.muted = true; p.play(); });
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const publish = async () => {
    if (busy) return;
    setBusy(true);
    try { await uploadClip(file, text.trim()); toast('Видео опубликовано'); onClose(); }
    catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не загрузилось', 'error'); }
    finally { setBusy(false); }
  };
  return (
    <Modal visible animationType="slide" onRequestClose={busy ? undefined : onClose} statusBarTranslucent>
      <KeyboardAvoidingView style={{ flex: 1, backgroundColor: '#000000' }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={{ flex: 1, marginTop: insets.top + 6, marginHorizontal: 6, borderRadius: radius.xl, overflow: 'hidden', backgroundColor: '#111111' }}>
          <VideoView player={player} contentFit="cover" nativeControls={false} playsInline style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }} />
          <View style={{ position: 'absolute', top: 10, left: 10 }}>
            <IconButton icon="close" label="Отмена" kind="plain" color="#FFFFFF" onPress={onClose} />
          </View>
          <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, padding: 16, paddingTop: 60,
            [Platform.OS === 'web' ? 'backgroundImage' : 'experimental_backgroundImage']: 'linear-gradient(to top, rgba(0,0,0,0.7), rgba(0,0,0,0))' } as any}>
            <TextInput value={text} onChangeText={setText} placeholder="Добавьте подпись…" placeholderTextColor="rgba(255,255,255,0.7)" multiline
              maxLength={500} accessibilityLabel="Подпись к видео"
              style={[T.body, { color: '#FFFFFF', fontSize: 17, minHeight: 28, outlineStyle: 'none', ...SHADOW } as any]} />
          </View>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingTop: 12, paddingBottom: insets.bottom + 12 }}>
          <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Icon name="pulseFill" size={20} color="#FFFFFF" />
            <Txt v="subhead" color="#FFFFFF" style={{ fontFamily: 'Onest_600SemiBold' }}>В Pulse</Txt>
          </View>
          <Tap onPress={publish} disabled={busy} haptic="medium" scaleTo={0.92} accessibilityLabel="Опубликовать"
            style={{ height: 48, paddingHorizontal: 22, borderRadius: 24, backgroundColor: c.accent, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            {busy ? <ActivityIndicator color={c.onAccent} /> : <Txt v="bodyStrong" color={c.onAccent}>Опубликовать</Txt>}
            {!busy ? <Icon name="arrowRight" size={18} color={c.onAccent} /> : null}
          </Tap>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

/** Pulse — вертикальные видео во весь экран, как в TikTok и Reels. */
export default function Pulse() {
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const toast = useToast();
  const q = usePulse();
  const clips = useMemo(() => q.data?.pages.flatMap((p) => p.clips) || [], [q.data]);
  const [file, setFile] = useState<PickedFile | null>(null);

  const add = useCallback(async () => {
    if (!user) { router.push('/login'); return; }
    const f = await pickMedia(['videos']);
    if (f && f.kind !== 'video') { toast('Выберите видео', 'error'); return; }
    if (f) setFile(f);
  }, [user, toast]);

  return (
    <>
      <ClipFeed
        clips={clips}
        // В браузере нижняя панель лежит поверх видео — подпись и кнопки поднимаем над ней
        bottom={Platform.OS === 'web' ? 54 + Math.max(insets.bottom, 6) : 0}
        onEndReached={() => { if (q.hasNextPage && !q.isFetchingNextPage) q.fetchNextPage(); }}
        refreshing={q.isRefetching}
        onRefresh={() => queryClient.resetQueries({ queryKey: PULSE_KEY, exact: true })}
        empty={q.isLoading ? (
          <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}><ActivityIndicator color="#FFFFFF" /></View>
        ) : (
          <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 14, paddingHorizontal: 36 }}>
            <Icon name="pulseFill" size={54} color="#FFFFFF" />
            <Txt v="title2" color="#FFFFFF" center>Здесь будут вертикальные видео</Txt>
            <Txt v="callout" color="rgba(255,255,255,0.7)" center>Снимите, что происходит вокруг: город, события, находки.</Txt>
            <Button title="Загрузить первое видео" kind="accent" icon="plus" full={false} onPress={add} />
          </View>
        )}
        overlay={
          <View pointerEvents="box-none" style={{ position: 'absolute', top: insets.top + 6, left: 0, right: 0, height: 44, alignItems: 'center', justifyContent: 'center' }}>
            <Txt v="headline" color="#FFFFFF" style={{ fontSize: 18, fontFamily: 'Onest_700Bold', ...SHADOW }}>Pulse</Txt>
            <View style={{ position: 'absolute', right: 8 }}>
              <IconButton icon="camera2" label="Загрузить видео" kind="plain" color="#FFFFFF" onPress={add} />
            </View>
          </View>
        }
      />
      {file ? <UploadScreen file={file} onClose={() => setFile(null)} /> : null}
    </>
  );
}

import * as ImagePicker from 'expo-image-picker';
import { router, useLocalSearchParams } from 'expo-router';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, TextInput, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { usePost } from '@/api/feed';
import { addStory, sharePostToStory, STORY_BG, storyGradient } from '@/api/stories';
import { PostSticker } from '@/features/stories/PostSticker';
import { pickMedia, PickedFile } from '@/lib/pickMedia';
import { type as T } from '@/theme';
import { Avatar, Icon, IconName, Img, Tap, Txt, useToast } from '@/ui';

const BGS = Object.keys(STORY_BG);
const SHADOW = { textShadowColor: 'rgba(0,0,0,0.45)', textShadowRadius: 6 };
const bgStyle = (bg: string) => ({ [Platform.OS === 'web' ? 'backgroundImage' : 'experimental_backgroundImage']: storyGradient(bg) } as any);

function Tool({ icon, label, onPress, active }: { icon: IconName; label: string; onPress: () => void; active?: boolean }) {
  return (
    <Tap onPress={onPress} scaleTo={0.88} accessibilityLabel={label}
      style={{ width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center',
        backgroundColor: active ? '#FFFFFF' : 'rgba(0,0,0,0.32)' }}>
      <Icon name={icon} size={21} color={active ? '#000000' : '#FFFFFF'} />
    </Tap>
  );
}

function VideoPreview({ uri }: { uri: string }) {
  const player = useVideoPlayer(uri, (p) => { p.loop = true; p.play(); });
  return <VideoView player={player} contentFit="cover" nativeControls={false} playsInline style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }} />;
}

/** Создание истории как в Instagram: выбор фото/видео во весь экран или пост-наклейка на градиенте,
 *  подпись поверх, внизу — «Ваша история» и круглая кнопка публикации. */
export default function StoryNew() {
  const { post } = useLocalSearchParams<{ post?: string }>();
  const postId = Number(post || 0);
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const toast = useToast();
  const p = usePost(postId);
  const [file, setFile] = useState<PickedFile | null>(null);
  const [bg, setBg] = useState(BGS[0]);
  const [caption, setCaption] = useState('');
  const [typing, setTyping] = useState(false);
  const [busy, setBusy] = useState(false);
  const close = () => (router.canGoBack() ? router.back() : router.replace('/'));

  const gallery = async () => {
    const f = await pickMedia(['images', 'videos'], 30);
    if (f) setFile(f);
  };
  const camera = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) { toast('Разрешите доступ к камере в настройках телефона', 'error'); return; }
    const r = await ImagePicker.launchCameraAsync({ mediaTypes: ['images', 'videos'], quality: 0.85, videoMaxDuration: 30 });
    const a = r.canceled ? null : r.assets?.[0];
    if (!a) return;
    const video = a.type === 'video';
    setFile({ uri: a.uri, name: a.fileName || (video ? 'story.mp4' : 'story.jpg'), type: a.mimeType || (video ? 'video/mp4' : 'image/jpeg'), kind: video ? 'video' : 'photo' });
  };
  const publish = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (postId) await sharePostToStory(postId, bg, caption.trim());
      else if (file) await addStory(file, caption.trim());
      toast('История опубликована на 24 часа');
      close();
    } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не получилось', 'error'); }
    finally { setBusy(false); }
  };

  const editing = postId > 0 || !!file;
  // Холст 9:16 по ширине экрана (на высоком телефоне), иначе по высоте
  const canvasH = Math.min(height - insets.top - insets.bottom - 86, (width - 12) * 16 / 9);

  if (!editing) {
    // Шаг 1: откуда история — галерея или камера (во весь экран, как «Добавить в историю» в Instagram)
    return (
      <View style={{ flex: 1, backgroundColor: '#000000', paddingTop: insets.top + 8, paddingBottom: insets.bottom + 16 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', height: 48, paddingHorizontal: 12 }}>
          <Tap onPress={close} scaleTo={0.88} accessibilityLabel="Закрыть" style={{ width: 44, height: 44, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="close" size={26} color="#FFFFFF" />
          </Tap>
          <Txt v="title3" color="#FFFFFF" center style={{ flex: 1, marginRight: 44 }}>Добавить в историю</Txt>
        </View>
        <View style={{ flexDirection: 'row', gap: 10, paddingHorizontal: 14, marginTop: 18 }}>
          {([['photo', 'Галерея', gallery], ['camera2', 'Камера', camera]] as [IconName, string, () => void][]).map(([icon, title, fn]) => (
            <Tap key={title} onPress={fn} scaleTo={0.96} accessibilityLabel={title}
              style={{ flex: 1, height: 120, borderRadius: 18, backgroundColor: '#1C1C1E', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
              <Icon name={icon} size={30} color="#FFFFFF" />
              <Txt v="bodyStrong" color="#FFFFFF">{title}</Txt>
            </Tap>
          ))}
        </View>
        <Tap onPress={gallery} scaleTo={0.99} accessibilityLabel="Выбрать фото или видео"
          style={{ flex: 1, margin: 14, marginTop: 14, borderRadius: 22, overflow: 'hidden', alignItems: 'center', justifyContent: 'center', gap: 14, ...bgStyle('night') }}>
          <View style={{ width: 84, height: 84, borderRadius: 42, borderWidth: 4, borderColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="plus" size={34} color="#FFFFFF" />
          </View>
          <Txt v="title3" color="#FFFFFF" center>Фото или видео</Txt>
          <Txt v="callout" color="rgba(255,255,255,0.75)" center style={{ paddingHorizontal: 30 }}>История видна 24 часа: друзьям и соседям из вашей страны</Txt>
        </Tap>
      </View>
    );
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: '#000000' }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={{ paddingTop: insets.top + 4, alignItems: 'center' }}>
        <View style={[{ width: width - 12, height: canvasH, borderRadius: 22, overflow: 'hidden', alignItems: 'center', justifyContent: 'center',
          backgroundColor: '#111111' }, postId ? bgStyle(bg) : null]}>
          {file?.kind === 'video' ? <VideoPreview uri={file.uri} />
            : file ? <Img source={file.uri} contentFit="cover" style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }} />
            : p.isLoading ? <ActivityIndicator color="#FFFFFF" />
            : <PostSticker post={p.data?.post ? { id: p.data.post.id, text: p.data.post.text, author: p.data.post.author,
                photo: p.data.post.photos[0] || '', ratio: p.data.post.ratio || 1, at: p.data.post.at } : null} width={Math.min(300, width * 0.72)} />}

          {/* Подпись поверх истории */}
          {typing || caption ? (
            <View style={{ position: 'absolute', left: 20, right: 20, bottom: 26, alignItems: 'center' }}>
              <TextInput value={caption} onChangeText={setCaption} autoFocus={typing} onBlur={() => setTyping(false)} placeholder="Добавьте подпись…"
                placeholderTextColor="rgba(255,255,255,0.7)" maxLength={200} multiline accessibilityLabel="Подпись к истории" textAlign="center"
                style={[T.bodyStrong, { color: '#FFFFFF', fontSize: 20, lineHeight: 26, textAlign: 'center', paddingHorizontal: 12, paddingVertical: 8,
                  borderRadius: 12, backgroundColor: 'rgba(0,0,0,0.35)', minWidth: 120, outlineStyle: 'none', ...SHADOW } as any]} />
            </View>
          ) : null}

          <View style={{ position: 'absolute', top: 12, left: 12 }}>
            <Tool icon="close" label="Отмена" onPress={() => (file && !postId ? setFile(null) : close())} />
          </View>
          <View style={{ position: 'absolute', top: 12, right: 12, gap: 12 }}>
            <Tool icon="textformat" label="Подпись" active={typing} onPress={() => setTyping(!typing)} />
            {postId ? <Tool icon="palette" label="Сменить фон" onPress={() => setBg(BGS[(BGS.indexOf(bg) + 1) % BGS.length])} /> : null}
            {!postId ? <Tool icon="photo" label="Выбрать другое" onPress={gallery} /> : null}
          </View>
        </View>
      </View>

      <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingBottom: insets.bottom }}>
        <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <View style={{ padding: 2, borderRadius: 22, borderWidth: 2, borderColor: '#FFFFFF' }}>
            {user ? <Avatar name={user.name} id={user.id} uri={user.avatar} size={34} /> : null}
          </View>
          <Txt v="bodyStrong" color="#FFFFFF">Ваша история</Txt>
        </View>
        <Tap onPress={publish} disabled={busy || (!!postId && p.isLoading)} haptic="medium" scaleTo={0.9} accessibilityLabel="Опубликовать историю"
          style={{ width: 56, height: 56, borderRadius: 28, backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' }}>
          {busy ? <ActivityIndicator color="#000000" /> : <Icon name="arrowRight" size={24} color="#000000" />}
        </Tap>
      </View>
    </KeyboardAvoidingView>
  );
}

import * as ImagePicker from 'expo-image-picker';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';
import { useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { createPost, feedChanged, MAX_POST_PHOTOS, usePost } from '@/api/feed';
import { shrinkForWeb } from '@/api/market';
import { PostPhotos, timeLabel } from '@/features/feed/cards';
import { radius, useTheme } from '@/theme';
import { Avatar, Button, Field, Icon, IconButton, Img, PageScreen, Tap, Txt, useToast } from '@/ui';

type Photo = { key: string; preview: string; payload: string };

export default function NewPost() {
  const { repost } = useLocalSearchParams<{ repost?: string }>();
  const repostId = Number(repost || 0);
  const { c } = useTheme();
  const { user } = useAuth();
  const toast = useToast();
  const orig = usePost(repostId);
  const [text, setText] = useState('');
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [busy, setBusy] = useState(false);

  const pick = async () => {
    const left = MAX_POST_PHOTOS - photos.length;
    if (left <= 0) return;
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7, base64: true,
      allowsMultipleSelection: true, selectionLimit: left, orderedSelection: true });
    if (r.canceled || !r.assets?.length) return;
    const added = await Promise.all(r.assets.slice(0, left).map(async (a, i) => ({
      key: `p${Date.now()}${i}`, preview: a.uri,
      payload: a.base64 ? `data:image/jpeg;base64,${a.base64}` : await shrinkForWeb(a.uri),
    })));
    setPhotos((cur) => [...cur, ...added].slice(0, MAX_POST_PHOTOS));
  };

  const ready = !!text.trim() || photos.length > 0 || repostId > 0;
  const publish = async () => {
    if (busy || !ready) return;
    setBusy(true);
    try {
      await createPost({ text: text.trim(), photos: photos.map((p) => p.payload), repost_of: repostId || undefined });
      feedChanged();
      toast(repostId ? 'Репост опубликован' : 'Пост опубликован');
      if (router.canGoBack()) router.back(); else router.replace('/');
    } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не опубликовалось', 'error'); }
    finally { setBusy(false); }
  };
  const o = orig.data?.post;
  const shown = o?.repost && !o.repost.deleted ? null : o;   // показываем то, чем делимся

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen title={repostId ? 'Поделиться' : 'Новый пост'}
        footer={<Button title={repostId ? 'Поделиться в ленте' : 'Опубликовать'} kind="primary" loading={busy} disabled={!ready} onPress={publish} />}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
          {user ? <Avatar name={user.name} id={user.id} size={46} /> : null}
          <View style={{ flex: 1 }}>
            <Txt v="headline">{user?.name || 'Новый пост'}</Txt>
            <Txt v="footnote">Увидят все в ленте{user?.city ? ` · ${user.city}` : ''}</Txt>
          </View>
        </View>
        <Field value={text} onChangeText={setText} multiline multilineHeight={repostId ? 110 : 180} maxLength={2000} autoFocus
          placeholder={repostId ? 'Добавьте пару слов (необязательно)' : 'Вопрос, совет, находка или история'} hint={`${text.length}/2000`} />
        {repostId ? (
          shown ? (
            <View style={{ borderRadius: radius.l, borderWidth: 1, borderColor: c.line, padding: 12, gap: 8 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <Avatar name={shown.author.name} id={shown.author.id} size={26} />
                <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold', flex: 1 }}>{shown.author.name}</Txt>
                <Txt v="caption">{timeLabel(shown.at)}</Txt>
              </View>
              {shown.text ? <Txt v="callout" tone="ink" numberOfLines={5}>{shown.text}</Txt> : null}
              <PostPhotos paths={shown.photos} />
            </View>
          ) : <Txt v="callout" tone="muted">{orig.isLoading ? 'Загружаем пост…' : 'Пост недоступен'}</Txt>
        ) : (
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
            {photos.map((p) => (
              <View key={p.key}>
                <Img source={p.preview} style={{ width: 84, height: 84, borderRadius: 16 }} />
                <View style={{ position: 'absolute', top: -8, right: -8 }}>
                  <IconButton icon="close" label="Убрать фото" size={30} onPress={() => setPhotos((cur) => cur.filter((x) => x.key !== p.key))} />
                </View>
              </View>
            ))}
            {photos.length < MAX_POST_PHOTOS ? (
              <Tap onPress={pick} scaleTo={0.94} accessibilityLabel="Добавить фото"
                style={{ width: 84, height: 84, borderRadius: 16, borderWidth: 1.5, borderStyle: 'dashed', borderColor: c.line,
                  alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                <Icon name="camera" size={22} color={c.muted} />
                <Txt v="caption">{photos.length ? `${photos.length}/${MAX_POST_PHOTOS}` : 'Фото'}</Txt>
              </Tap>
            ) : null}
          </View>
        )}
        <Txt v="footnote">Без мата, политики и рекламы — см. правила сообщества.</Txt>
      </PageScreen>
    </KeyboardAvoidingView>
  );
}

import * as ImagePicker from 'expo-image-picker';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { createPost, feedChanged, MAX_POST_PHOTOS, usePost } from '@/api/feed';
import { ItemRef, shareItem } from '@/api/items';
import { shrinkForWeb } from '@/api/market';
import { CitySheet } from '@/features/common/CitySheet';
import { PostPhotos } from '@/features/feed/FeedItems';
import { timeLabel } from '@/features/feed/cards';
import { useCountry } from '@/lib/useCity';
import { HAIRLINE, radius, type as T, useTheme } from '@/theme';
import { Avatar, BAR_H, Icon, IconButton, Img, Tap, TopBar, Txt, useScrollY, useToast } from '@/ui';

type Photo = { key: string; preview: string; payload: string };
const MAX_TEXT = 2000;

/** Новый пост в духе Threads: аватар и имя, текст прямо на фоне экрана, под ним — тонкие иконки, «Опубликовать» в шапке. */
export default function NewPost() {
  const { repost, share } = useLocalSearchParams<{ repost?: string; share?: string }>();
  const repostId = Number(repost || 0);
  // «Поделиться с комментарием» новостью или событием: их данные приходят параметром
  const item = (() => { try { return share ? (JSON.parse(share) as ItemRef) : null; } catch { return null; } })();
  const sharing = repostId > 0 || !!item;
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const country = useCountry();
  const toast = useToast();
  const orig = usePost(repostId);
  const { y, onScroll } = useScrollY();
  const [text, setText] = useState('');
  const [height, setHeight] = useState(0);
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [city, setCity] = useState('');
  const [picker, setPicker] = useState(false);
  const [busy, setBusy] = useState(false);

  const pick = async () => {
    const left = MAX_POST_PHOTOS - photos.length;
    if (left <= 0) { toast(`Можно до ${MAX_POST_PHOTOS} фото`); return; }
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7, base64: true,
      allowsMultipleSelection: true, selectionLimit: left, orderedSelection: true });
    if (r.canceled || !r.assets?.length) return;
    const added = await Promise.all(r.assets.slice(0, left).map(async (a, i) => ({
      key: `p${Date.now()}${i}`, preview: a.uri,
      payload: a.base64 ? `data:image/jpeg;base64,${a.base64}` : await shrinkForWeb(a.uri),
    })));
    setPhotos((cur) => [...cur, ...added].slice(0, MAX_POST_PHOTOS));
  };

  const ready = !!text.trim() || photos.length > 0 || sharing;
  const publish = async () => {
    if (busy || !ready) return;
    setBusy(true);
    try {
      if (item) await shareItem(item, text.trim());
      else await createPost({ text: text.trim(), photos: photos.map((p) => p.payload), repost_of: repostId || undefined, city: city || undefined });
      feedChanged();
      toast(sharing ? 'Теперь это в вашем профиле' : 'Пост опубликован');
      if (router.canGoBack()) router.back(); else router.replace('/');
    } catch (e: any) { if (!routeForError(e)) toast(e?.message || 'Не опубликовалось', 'error'); }
    finally { setBusy(false); }
  };
  const o = orig.data?.post;
  const shown = o?.repost && !o.repost.deleted ? null : o;   // показываем то, чем делимся
  const place = city || user?.city || '';

  const publishBtn = (
    <Tap onPress={publish} disabled={!ready || busy} haptic="light" scaleTo={0.94} accessibilityLabel={sharing ? 'Поделиться' : 'Опубликовать'}
      style={{ height: 34, minWidth: 112, paddingHorizontal: 16, borderRadius: radius.pill, alignItems: 'center', justifyContent: 'center',
        backgroundColor: ready ? c.accent : c.bgSunken }}>
      {busy ? <ActivityIndicator size="small" color={c.onAccent} /> : (
        <Txt v="subhead" color={ready ? c.onAccent : c.faint} style={{ fontFamily: 'Onest_700Bold' }}>{sharing ? 'Поделиться' : 'Опубликовать'}</Txt>
      )}
    </Tap>
  );

  return (
    <KeyboardAvoidingView style={{ flex: 1, backgroundColor: c.bg }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView onScroll={onScroll} scrollEventThrottle={16} keyboardShouldPersistTaps="handled" keyboardDismissMode="interactive"
        contentContainerStyle={{ paddingTop: insets.top + BAR_H + 10, paddingHorizontal: 16, paddingBottom: insets.bottom + 40 }}>
        <View style={{ flexDirection: 'row', gap: 12 }}>
          {/* Колонка аватара с тонкой линией, как в Threads */}
          <View style={{ alignItems: 'center', gap: 8 }}>
            {user ? <Avatar name={user.name} id={user.id} uri={user.avatar} size={40} /> : null}
            <View style={{ flex: 1, width: 2, borderRadius: 1, backgroundColor: c.line, minHeight: 24 }} />
          </View>

          <View style={{ flex: 1, minWidth: 0, gap: 10 }}>
            <View style={{ gap: 1, paddingTop: 1 }}>
              <Txt v="bodyStrong" numberOfLines={1}>{user?.name || 'Новый пост'}</Txt>
              {place ? (
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                  <Icon name="location" thin size={13} color={city ? c.accentText : c.faint} />
                  <Txt v="footnote" color={city ? c.accentText : c.faint}>{place}</Txt>
                </View>
              ) : null}
            </View>

            <TextInput value={text} onChangeText={(t) => setText(t.slice(0, MAX_TEXT))} multiline autoFocus scrollEnabled={false}
              placeholder={sharing ? 'Добавьте пару слов (необязательно)' : 'Делитесь новостями...'} placeholderTextColor={c.faint}
              onContentSizeChange={(e) => setHeight(e.nativeEvent.contentSize.height)} accessibilityLabel="Текст поста"
              style={[T.body, { color: c.ink, fontSize: 17, lineHeight: 25, padding: 0, margin: 0, minHeight: 50,
                height: Platform.OS === 'web' ? Math.max(50, height) : undefined, textAlignVertical: 'top', outlineStyle: 'none' } as any]} />

            {item ? (
              <View style={{ flexDirection: 'row', gap: 12, alignItems: 'center', borderRadius: 8, backgroundColor: c.bgSunken, padding: 12 }}>
                {item.img ? <Img source={item.img} style={{ width: 64, height: 64, borderRadius: 8 }} /> : null}
                <View style={{ flex: 1, gap: 3 }}>
                  <Txt v="caption" tone="accent" style={{ fontFamily: 'Onest_700Bold' }}>{item.kind === 'event' ? 'Событие' : 'Новость'}</Txt>
                  <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }}>{item.title}</Txt>
                </View>
              </View>
            ) : repostId ? (
              shown ? (
                <View style={{ borderRadius: 8, backgroundColor: c.bgSunken, padding: 12, gap: 8 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                    <Avatar name={shown.author.name} id={shown.author.id} uri={shown.author.avatar} size={26} />
                    <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold', flex: 1 }}>{shown.author.name}</Txt>
                    <Txt v="caption">{timeLabel(shown.at)}</Txt>
                  </View>
                  {shown.text ? <Txt v="callout" tone="ink" numberOfLines={5}>{shown.text}</Txt> : null}
                  <PostPhotos paths={shown.photos} />
                </View>
              ) : <Txt v="callout" tone="muted">{orig.isLoading ? 'Загружаем пост…' : 'Пост недоступен'}</Txt>
            ) : photos.length ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginRight: -16 }}
                contentContainerStyle={{ gap: 8, paddingRight: 16 }}>
                {photos.map((p) => (
                  <View key={p.key}>
                    <Img source={p.preview} style={{ width: photos.length === 1 ? 240 : 168, height: photos.length === 1 ? 300 : 220, borderRadius: 14,
                      borderWidth: HAIRLINE, borderColor: c.line }} />
                    <Tap onPress={() => setPhotos((cur) => cur.filter((x) => x.key !== p.key))} scaleTo={0.88} accessibilityLabel="Убрать фото"
                      style={{ position: 'absolute', top: 8, right: 8, width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center',
                        backgroundColor: 'rgba(0,0,0,0.6)' }}>
                      <Icon name="close" size={14} color="#FFFFFF" />
                    </Tap>
                  </View>
                ))}
              </ScrollView>
            ) : null}

            {/* Инструменты прямо под текстом */}
            {!sharing ? (
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, marginLeft: -8 }}>
                <IconButton icon="photo" kind="plain" size={40} label="Добавить фото" onPress={pick}
                  color={photos.length >= MAX_POST_PHOTOS ? c.faint : c.muted} />
                <IconButton icon="location" kind="plain" size={40} label={city ? `Город: ${city}` : 'Выбрать город'} onPress={() => setPicker(true)}
                  color={city ? c.accent : c.muted} />
                {photos.length ? <Txt v="caption" style={{ marginLeft: 4 }}>{photos.length}/{MAX_POST_PHOTOS} фото</Txt> : null}
                <View style={{ flex: 1 }} />
                {text.length > MAX_TEXT - 200 ? (
                  <Txt v="caption" color={text.length >= MAX_TEXT ? c.danger : c.faint} style={{ fontVariant: ['tabular-nums'] }}>{MAX_TEXT - text.length}</Txt>
                ) : null}
              </View>
            ) : null}
          </View>
        </View>

        <Txt v="footnote" color={c.faint} style={{ marginTop: 22, marginLeft: 52 }}>Без мата, политики и рекламы — см. правила сообщества.</Txt>
      </ScrollView>

      <TopBar y={y} always title={sharing ? 'Поделиться' : 'Новый пост'}
        left={<IconButton icon="close" kind="plain" label="Закрыть" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} />}
        right={publishBtn} />
      <CitySheet visible={picker} value={city} country={country} onPick={setCity} onClose={() => setPicker(false)}
        extra={[user?.city || '']} allLabel={user?.city ? `Как в профиле (${user.city})` : 'Без города'} />
    </KeyboardAvoidingView>
  );
}

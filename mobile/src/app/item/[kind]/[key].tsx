import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';
import { useAuth } from '@/api/auth';
import { removeOwn, report, routeForError } from '@/api/community';
import { Comment } from '@/api/feed';
import { addItemComment, itemId, ItemKind, ItemRef, shareItem, statsOf, toggleItemLike, useItemComments, useItemStats } from '@/api/items';
import { queryClient } from '@/api/query';
import { Composer } from '@/features/chat/ChatUI';
import { timeLabel } from '@/features/feed/cards';
import { ActionBar } from '@/features/feed/FeedItems';
import { openUrl } from '@/lib/open';
import { radius, useTheme } from '@/theme';
import { ActionSheet, Empty, handle, Img, PageScreen, Skeleton, Tap, Txt, UserAvatar, useToast } from '@/ui';

/** Обсуждение новости или события из ленты: превью, лайк, «поделиться в профиле», комментарии. */
export default function ItemScreen() {
  const prm = useLocalSearchParams<{ kind: ItemKind; key: string; title?: string; url?: string; img?: string }>();
  const it: ItemRef = { kind: prm.kind === 'event' ? 'event' : 'news', key: String(prm.key), title: prm.title || '', url: prm.url || '', img: prm.img || '' };
  const { c } = useTheme();
  const { user } = useAuth();
  const toast = useToast();
  const id = itemId(it.kind, it.key);
  const stats = useItemStats([id]);
  const s = statsOf(stats.data, id);
  const q = useItemComments(it.kind, it.key);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [sheet, setSheet] = useState<Comment | null>(null);
  const fail = (e: any) => { if (!routeForError(e)) toast(e?.message || 'Не получилось', 'error'); };
  const open = () => (it.kind === 'event' ? router.push({ pathname: '/event/[key]', params: { key: it.key } }) : it.url ? openUrl(it.url) : undefined);
  const send = async () => {
    const t = text.trim();
    if (!t || busy) return;
    if (!user) return router.push('/login');
    setBusy(true);
    try { await addItemComment(it.kind, it.key, t); setText(''); } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const drop = (cm: Comment) => removeOwn('icomment', cm.id).then(() => {
    queryClient.setQueryData<Comment[]>(['items', 'comments', it.kind, it.key], (cur) => (cur || []).filter((x) => x.id !== cm.id));
    stats.refetch();
  }).catch(fail);

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen title={it.kind === 'event' ? 'Событие' : 'Новость'} bg={c.bgElevated}
        footer={<Composer value={text} onChange={setText} onSend={send} busy={busy}
          placeholder={user ? 'Комментарий' : 'Войдите, чтобы комментировать'} onFocus={() => { if (!user) router.push('/login'); }} />}>
        <Tap onPress={open} scaleTo={0.99} style={{ gap: 12 }} accessibilityRole="link">
          {it.img ? <Img source={it.img} style={{ width: '100%', aspectRatio: 16 / 10, borderRadius: radius.l }} /> : null}
          <Txt v="overline" tone="accent">{it.kind === 'event' ? 'Афиша' : 'Новости podslushano.nl'}</Txt>
          <Txt v="title2">{it.title}</Txt>
          <Txt v="subhead" tone="accent" style={{ fontFamily: 'Onest_600SemiBold' }}>{it.kind === 'event' ? 'Подробнее о событии' : 'Читать на сайте'}</Txt>
        </Tap>
        <ActionBar likes={s.likes} liked={s.liked} comments={s.comments} reposts={s.shares} reposted={s.shared}
          onLike={() => (user ? toggleItemLike(it.kind, it.key, s).catch(fail) : router.push('/login'))}
          onComment={() => {}}
          onRepost={() => (!user ? router.push('/login') : s.shared ? toast('Уже в вашем профиле')
            : shareItem(it).then(() => toast('Теперь это в вашем профиле')).catch(fail))} />
        <View style={{ height: 1, backgroundColor: c.line }} />
        <Txt v="overline">{q.data?.length ? `Комментарии · ${q.data.length}` : 'Комментарии'}</Txt>
        {q.isLoading ? <Skeleton h={60} r={16} /> : q.data?.length ? (
          <View style={{ gap: 18 }}>
            {q.data.map((cm) => (
              <Tap key={cm.id} onLongPress={() => (user ? setSheet(cm) : undefined)} scaleTo={0.99} style={{ flexDirection: 'row', gap: 12 }}
                accessibilityHint="Удерживайте для действий">
                <UserAvatar u={cm.author} size={34} />
                <View style={{ flex: 1, gap: 2 }}>
                  <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_700Bold' }}>{handle(cm.author)} <Txt v="caption">{timeLabel(cm.at)}</Txt></Txt>
                  <Txt v="callout" tone="ink" selectable>{cm.text}</Txt>
                </View>
              </Tap>
            ))}
          </View>
        ) : <Empty icon="bubble" title="Будьте первым" text="Обсудите это с другими участниками." />}
      </PageScreen>
      <ActionSheet visible={!!sheet} onClose={() => setSheet(null)} actions={sheet ? (sheet.mine
        ? [{ title: 'Удалить комментарий', icon: 'trash', danger: true, onPress: () => drop(sheet) }]
        : [{ title: 'Пожаловаться', icon: 'flag', danger: true, onPress: () => report('icomment', sheet.id).then(() => toast('Жалоба отправлена модераторам')).catch(fail) }]) : []} />
    </KeyboardAvoidingView>
  );
}

import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';
import { useAuth } from '@/api/auth';
import { removeOwn, report, routeForError } from '@/api/community';
import { addComment, Comment, patchPost, usePost } from '@/api/feed';
import { queryClient } from '@/api/query';
import { Composer } from '@/features/chat/ChatUI';
import { relTime } from '@/lib/format';
import { FeedPost } from '@/features/feed/FeedItems';
import { usePostMenu } from '@/features/feed/usePostMenu';
import { ActionSheet, Empty, handle, PageScreen, Skeleton, Tap, Txt, useToast, UserAvatar, VerifiedBadge } from '@/ui';

/** Комментарий как в Instagram: аватар, @username с галочкой и время, ниже текст — без «пузыря». */
function CommentRow({ c: cm, onLong }: { c: Comment; onLong: () => void }) {
  return (
    <View style={{ flexDirection: 'row', gap: 12, alignItems: 'flex-start' }}>
      <Tap onPress={() => router.push({ pathname: '/user/[id]', params: { id: String(cm.author.id) } })} scaleTo={0.92}
        accessibilityLabel={`Профиль: ${handle(cm.author)}`}>
        <UserAvatar u={cm.author} size={34} />
      </Tap>
      <Tap onLongPress={onLong} scaleTo={0.99} haptic={false} accessibilityHint="Удерживайте для действий" style={{ flex: 1, gap: 3 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', flexShrink: 1 }}>
            <Txt v="footnote" tone="ink" numberOfLines={1} style={{ fontFamily: 'Onest_700Bold', flexShrink: 1 }}>{handle(cm.author)}</Txt>
            {cm.author.verified ? <VerifiedBadge size={12} /> : null}
          </View>
          <Txt v="caption" tone="muted">{relTime(cm.at)}</Txt>
        </View>
        <Txt v="subhead" tone="ink" selectable style={{ lineHeight: 20 }}>{cm.text}</Txt>
      </Tap>
    </View>
  );
}

export default function PostScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const pid = Number(id);
  const { user } = useAuth();
  const toast = useToast();
  const q = usePost(pid);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [sheet, setSheet] = useState<Comment | null>(null);
  const { openMenu, sheet: postSheet } = usePostMenu(() => (router.canGoBack() ? router.back() : router.replace('/')));
  const fail = (e: any) => { if (!routeForError(e)) toast(e?.message || 'Ошибка', 'error'); };

  const send = async () => {
    const t = text.trim();
    if (!t || busy) return;
    if (!user) return router.push('/login');
    setBusy(true);
    try { await addComment(pid, t); setText(''); } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const drop = (cm: Comment) => removeOwn('comment', cm.id).then(() => {
    queryClient.setQueryData<any>(['post', pid], (d: any) => d && { ...d, comments: d.comments.filter((x: Comment) => x.id !== cm.id) });
    patchPost(pid, (x) => ({ ...x, comments: Math.max(0, x.comments - 1) }));
  }).catch(fail);

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <PageScreen title="Пост" refreshing={q.isRefetching} onRefresh={() => q.refetch()}
        footer={q.data ? <Composer value={text} onChange={setText} onSend={send} busy={busy}
          placeholder={user ? 'Комментарий' : 'Войдите, чтобы комментировать'} onFocus={() => { if (!user) router.push('/login'); }} /> : undefined}>
        {q.isLoading ? <Skeleton h={220} r={28} /> : !q.data ? (
          <Empty icon="bubble" title="Пост удалён или недоступен" />
        ) : (
          <>
            <View style={{ marginHorizontal: -20 }}><FeedPost p={q.data.post} full onMenu={() => openMenu(q.data!.post)} /></View>
            <Txt v="overline" style={{ marginLeft: 6 }}>{q.data.comments.length ? `Комментарии · ${q.data.comments.length}` : 'Комментариев пока нет'}</Txt>
            <View style={{ gap: 18 }}>
              {q.data.comments.map((cm) => <CommentRow key={cm.id} c={cm} onLong={() => (user ? setSheet(cm) : router.push('/login'))} />)}
            </View>
          </>
        )}
      </PageScreen>
      {postSheet}
      <ActionSheet visible={!!sheet} onClose={() => setSheet(null)} actions={sheet ? (sheet.mine
        ? [{ title: 'Удалить комментарий', icon: 'trash', danger: true, onPress: () => drop(sheet) }]
        : [{ title: 'Пожаловаться', icon: 'flag', danger: true, onPress: () => report('comment', sheet.id).then(() => toast('Жалоба отправлена модераторам')).catch(fail) }]) : []} />
    </KeyboardAvoidingView>
  );
}

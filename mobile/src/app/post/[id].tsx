import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, View } from 'react-native';
import { useAuth } from '@/api/auth';
import { removeOwn, report, routeForError } from '@/api/community';
import { addComment, Comment, patchPost, usePost } from '@/api/feed';
import { queryClient } from '@/api/query';
import { Composer } from '@/features/chat/ChatUI';
import { timeLabel } from '@/features/feed/cards';
import { FeedPost } from '@/features/feed/FeedItems';
import { usePostMenu } from '@/features/feed/usePostMenu';
import { radius, useTheme } from '@/theme';
import { ActionSheet, Avatar, Empty, PageScreen, Skeleton, Tap, Txt, useToast, VerifiedBadge } from '@/ui';

function CommentRow({ c: cm, onLong }: { c: Comment; onLong: () => void }) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start' }}>
      <Tap onPress={() => router.push({ pathname: '/user/[id]', params: { id: String(cm.author.id) } })} scaleTo={0.92}
        accessibilityLabel={`Профиль: ${cm.author.name}`}>
        <Avatar name={cm.author.name} id={cm.author.id} uri={cm.author.avatar} size={34} />
      </Tap>
      <Tap onLongPress={onLong} scaleTo={0.99} accessibilityHint="Удерживайте для действий"
        style={{ flex: 1, backgroundColor: c.bgElevated, borderRadius: radius.l, borderTopLeftRadius: 6, padding: 12, gap: 3, borderWidth: 1, borderColor: c.line }}>
        <View style={{ flexDirection: 'row', gap: 8, alignItems: 'baseline' }}>
          <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center' }}>
            <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_700Bold', flexShrink: 1 }} numberOfLines={1}>{cm.author.name}</Txt>
            {cm.author.verified ? <VerifiedBadge size={13} /> : null}
          </View>
          <Txt v="caption">{timeLabel(cm.at)}</Txt>
        </View>
        <Txt v="callout" tone="ink" selectable>{cm.text}</Txt>
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
            <FeedPost p={q.data.post} full onMenu={() => openMenu(q.data!.post)} />
            <Txt v="overline" style={{ marginLeft: 6 }}>{q.data.comments.length ? `Комментарии · ${q.data.comments.length}` : 'Комментариев пока нет'}</Txt>
            <View style={{ gap: 10 }}>
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

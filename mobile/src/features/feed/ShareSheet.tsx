import { router } from 'expo-router';
import { useState } from 'react';
import { Modal, Platform, Pressable, ScrollView, Share as RNShare, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@/api/auth';
import { BOT } from '@/api/client';
import { sendDm } from '@/api/dm';
import { startChat, useFriends } from '@/api/social';
import { radius, useTheme } from '@/theme';
import { handle, Icon, IconName, Tap, Txt, useToast, UserAvatar } from '@/ui';

/** Ссылка на пост: системное «Поделиться» или копия в буфер (в браузере). true — ссылка скопирована. */
export async function sharePostLink(id: number): Promise<boolean> {
  const url = `${BOT}/app/post/${id}`;
  try {
    if (Platform.OS !== 'web') { await RNShare.share({ message: url }); return false; }
    const nav = (globalThis as any).navigator;
    if (nav?.share) { await nav.share({ title: 'podslushano.nl', url }); return false; }
    await nav?.clipboard?.writeText(url);
    return true;
  } catch { return false; }
}

function Round({ icon, title, onPress, tint }: { icon: IconName; title: string; onPress: () => void; tint?: string }) {
  const { c } = useTheme();
  return (
    <Tap onPress={onPress} scaleTo={0.92} accessibilityLabel={title} style={{ alignItems: 'center', gap: 7, width: 76 }}>
      <View style={{ width: 56, height: 56, borderRadius: 28, backgroundColor: tint || c.bgSunken, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name={icon} size={24} color={tint ? '#FFFFFF' : c.ink} />
      </View>
      <Txt v="caption" tone="ink" center numberOfLines={2}>{title}</Txt>
    </Tap>
  );
}

/** «Поделиться» как в Instagram: сверху друзья (отправить пост в личные сообщения одним касанием),
 *  ниже — в историю, репост в профиль, репост с комментарием и ссылка. */
export function ShareSheet({ visible, onClose, postId, reposted, canRepost, onRepost }: {
  visible: boolean; onClose: () => void; postId: number; reposted?: boolean; canRepost?: boolean; onRepost?: (on: boolean) => void;
}) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { user } = useAuth();
  const friends = useFriends(visible && !!user);
  const [sent, setSent] = useState<Record<number, 'busy' | 'ok'>>({});
  const go = (fn: () => void) => { onClose(); setTimeout(fn, Platform.OS === 'ios' ? 250 : 0); };
  const needLogin = () => go(() => router.push('/login'));
  const send = async (uid: number) => {
    if (sent[uid]) return;
    setSent((s) => ({ ...s, [uid]: 'busy' }));
    try {
      const { id } = await startChat(uid);
      await sendDm(id, `${BOT}/app/post/${postId}`);
      setSent((s) => ({ ...s, [uid]: 'ok' }));
    } catch (e: any) {
      setSent((s) => { const n = { ...s }; delete n[uid]; return n; });
      toast(e?.message || 'Не отправилось', 'error');
    }
  };
  const list = friends.data?.friends || [];
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <Pressable style={{ flex: 1, backgroundColor: c.scrim, justifyContent: 'flex-end' }} onPress={onClose} accessibilityLabel="Закрыть">
        <Pressable onPress={() => {}} style={{ backgroundColor: c.bgElevated, borderTopLeftRadius: radius.xl, borderTopRightRadius: radius.xl,
          paddingTop: 8, paddingBottom: insets.bottom + 14, gap: 14 }}>
          <View style={{ alignSelf: 'center', width: 38, height: 5, borderRadius: 3, backgroundColor: c.line }} />
          <Txt v="headline" center>Поделиться</Txt>
          {user && list.length ? (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 12, gap: 4 }}>
              {list.map((f) => {
                const st = sent[f.id];
                return (
                  <Tap key={f.id} onPress={() => send(f.id)} scaleTo={0.94} accessibilityLabel={`Отправить ${handle(f)}`}
                    style={{ width: 80, alignItems: 'center', gap: 6 }}>
                    <View>
                      <UserAvatar u={f} size={62} />
                      {st === 'ok' ? (
                        <View style={{ position: 'absolute', right: -2, bottom: -2, width: 24, height: 24, borderRadius: 12, backgroundColor: c.accent,
                          borderWidth: 2, borderColor: c.bgElevated, alignItems: 'center', justifyContent: 'center' }}>
                          <Icon name="check" size={13} color={c.onAccent} />
                        </View>
                      ) : null}
                    </View>
                    <Txt v="caption" tone="ink" numberOfLines={1}>{st === 'ok' ? 'Отправлено' : st === 'busy' ? 'Отправка…' : handle(f)}</Txt>
                  </Tap>
                );
              })}
            </ScrollView>
          ) : null}
          <View style={{ height: 1, backgroundColor: c.line, marginHorizontal: 16 }} />
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 10, gap: 2 }}>
            <Round icon="plus" title="В историю" tint={c.accent}
              onPress={() => (user ? go(() => router.push({ pathname: '/story-new', params: { post: String(postId) } })) : needLogin())} />
            {canRepost && onRepost ? (
              <Round icon="repost" title={reposted ? 'Убрать репост' : 'Репост'} onPress={() => (user ? go(() => onRepost(!reposted)) : needLogin())} />
            ) : null}
            {canRepost && !reposted ? (
              <Round icon="edit" title="С комментарием"
                onPress={() => (user ? go(() => router.push({ pathname: '/new-post', params: { repost: String(postId) } })) : needLogin())} />
            ) : null}
            <Round icon="share" title="Ссылка" onPress={() => go(() => sharePostLink(postId).then((copied) => { if (copied) toast('Ссылка скопирована'); }))} />
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

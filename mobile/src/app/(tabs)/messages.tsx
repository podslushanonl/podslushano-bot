import { router } from 'expo-router';
import { useState } from 'react';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { Room, useRooms } from '@/api/community';
import { Conversation, useConversations } from '@/api/dm';
import { photoUrl } from '@/api/market';
import { timeLabel } from '@/features/feed/cards';
import { useFriends } from '@/api/social';
import { useCity, useCountry } from '@/lib/useCity';
import { radius, useTheme } from '@/theme';
import { Avatar, Badge, Button, Empty, Group, Icon, Img, Row, Segmented, Skeleton, TabScreen, Tap, Txt } from '@/ui';

function ConversationRow({ cv, first }: { cv: Conversation; first: boolean }) {
  const { c } = useTheme();
  return (
    <Tap onPress={() => router.push({ pathname: '/dm/[id]', params: { id: String(cv.id) } })} scaleTo={0.99}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 13, borderTopWidth: first ? 0 : 1, borderTopColor: c.line }}>
      <View>
        <Avatar name={cv.peer.name} id={cv.peer.id} size={52} />
        {cv.listing?.photo ? <Img source={photoUrl(cv.listing)} style={{ position: 'absolute', right: -4, bottom: -4, width: 26, height: 26, borderRadius: 8, borderWidth: 2, borderColor: c.bgElevated }} /> : null}
      </View>
      <View style={{ flex: 1, gap: 2 }}>
        <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 8 }}>
          <Txt v="headline" style={{ flex: 1 }} numberOfLines={1}>{cv.peer.name}</Txt>
          {cv.last ? <Txt v="caption" tone={cv.unread ? 'ink' : 'muted'}>{timeLabel(cv.last.at)}</Txt> : null}
        </View>
        {cv.listing ? <Txt v="caption" numberOfLines={1}>{cv.listing.title}{cv.listing.price ? ` · ${cv.listing.price}` : ''}</Txt> : null}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Txt v="subhead" tone={cv.unread ? 'ink' : 'muted'} numberOfLines={1} style={{ flex: 1, fontFamily: cv.unread ? 'Onest_600SemiBold' : 'Onest_500Medium' }}>
            {cv.last ? `${cv.last.mine ? 'Вы: ' : ''}${cv.last.text}` : 'Новый диалог'}
          </Txt>
          <Badge n={cv.unread} />
        </View>
      </View>
    </Tap>
  );
}

function RoomsList({ rooms: all }: { rooms: Room[] }) {
  const { c } = useTheme();
  const [city] = useCity();
  const country = useCountry();
  // Общие комнаты (для всех стран) и комнаты своей страны
  const common = all.filter((r) => !r.country);
  const rooms = all.filter((r) => r.country === country);
  const mine = rooms.find((r) => r.kind === 'city' && r.title === city);
  const open = (r: Room) => router.push({ pathname: '/room/[slug]', params: { slug: r.slug, title: r.title } });
  return (
    <View style={{ gap: 18 }}>
      {common.length ? (
        <Group title="Для всех · Нидерланды, Германия, Бельгия">
          {common.map((r, i) => (
            <Row key={r.slug} first={i === 0} title={r.title} sub={r.today ? `${r.today} сообщ. за сутки` : 'Общайтесь со всеми — дружба не нужна'}
              icon="globe" onPress={() => open(r)} />
          ))}
        </Group>
      ) : null}
      {mine ? (
        <Tap onPress={() => open(mine)} scaleTo={0.98} style={{ backgroundColor: c.hero, borderRadius: radius.xxl, padding: 18, gap: 12 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <View style={{ width: 44, height: 44, borderRadius: 15, backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center' }}>
              <Icon name="location" size={20} color={c.onAccent} />
            </View>
            <View style={{ flex: 1 }}>
              <Txt v="overline" color={c.accent}>Ваш город</Txt>
              <Txt v="title2" color={c.onHero}>{mine.title}</Txt>
            </View>
            <Icon name="chevron" size={14} color={c.onHeroMuted} />
          </View>
          <Txt v="callout" color={c.onHeroMuted}>{mine.today ? `${mine.today} сообщений за сутки — присоединяйтесь` : 'Начните разговор с соседями'}</Txt>
        </Tap>
      ) : null}
      <Group title="Города">
        {rooms.filter((r) => r.kind === 'city' && r !== mine).map((r, i) => (
          <Row key={r.slug} first={i === 0} title={r.title} sub={r.today ? `${r.today} сообщ. за сутки` : 'Тихо — начните разговор'} icon="location" onPress={() => open(r)} />
        ))}
      </Group>
      <Group title="Темы">
        {rooms.filter((r) => r.kind === 'topic').map((r, i) => (
          <Row key={r.slug} first={i === 0} title={r.title} sub={r.today ? `${r.today} сообщ. за сутки` : country} icon="people" onPress={() => open(r)} />
        ))}
      </Group>
      <Txt v="footnote" center>Будьте вежливы: у нас есть модерация. Правила — в профиле.</Txt>
    </View>
  );
}

export default function Messages() {
  const { user } = useAuth();
  const [tab, setTab] = useState<'dm' | 'rooms'>(user ? 'dm' : 'rooms');
  const rooms = useRooms();
  const dms = useConversations(!!user);
  const friends = useFriends(!!user);
  const requests = friends.data?.incoming.length || 0;
  return (
    <TabScreen title="Сообщения" refreshing={rooms.isRefetching || dms.isRefetching}
      onRefresh={() => { rooms.refetch(); if (user) { dms.refetch(); friends.refetch(); } }}>
      <Segmented value={tab} onChange={setTab} items={[
        { key: 'dm', title: dms.data?.unread ? `Личные · ${dms.data.unread}` : 'Личные' },
        { key: 'rooms', title: 'Общие чаты' },
      ]} />
      {tab === 'rooms' ? (
        rooms.data ? <RoomsList rooms={rooms.data} /> : <View style={{ gap: 10 }}><Skeleton h={120} r={34} /><Skeleton h={260} r={22} /></View>
      ) : !user ? (
        <Empty icon="bubble" title="Личные сообщения" text="Переписывайтесь с друзьями прямо в приложении — без обмена телефонами."
          action={<Button title="Войти" kind="primary" onPress={() => router.push('/login')} />} />
      ) : (
        <>
          <Group>
            <Row first title="Друзья" sub={requests ? `Новые заявки в друзья: ${requests}` : 'Личные сообщения — для друзей'}
              icon="people" right={<Badge n={requests} />} onPress={() => router.push('/friends')} />
          </Group>
          {dms.isLoading ? (
            <View style={{ gap: 10 }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={74} r={22} />)}</View>
          ) : dms.data?.items.length ? (
            <Group>{dms.data.items.map((cv, i) => <ConversationRow key={cv.id} cv={cv} first={i === 0} />)}</Group>
          ) : (
            <Empty icon="bubble" title="Пока нет диалогов" text="Добавьте человека в друзья — и пишите друг другу. Найти людей можно по имени или в общих чатах."
              action={<Button title="Найти друзей" kind="secondary" onPress={() => router.push('/friends')} />} />
          )}
        </>
      )}
    </TabScreen>
  );
}

import { router } from 'expo-router';
import { ReactNode, useState } from 'react';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { Room, useRooms } from '@/api/community';
import { Conversation, useConversations } from '@/api/dm';
import { photoUrl } from '@/api/market';
import { timeLabel } from '@/features/feed/cards';
import { useFriends } from '@/api/social';
import { useCity, useCountry } from '@/lib/useCity';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Avatar, Badge, Button, Empty, Group, Icon, IconName, Img, Row, Segmented, Skeleton, TabScreen, Tap, Txt } from '@/ui';

function ConversationRow({ cv, first }: { cv: Conversation; first: boolean }) {
  const { c } = useTheme();
  return (
    <Tap onPress={() => router.push({ pathname: '/dm/[id]', params: { id: String(cv.id) } })} scaleTo={0.99}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 13, borderTopWidth: first ? 0 : 1, borderTopColor: c.line }}>
      <View>
        <Avatar name={cv.peer.name} id={cv.peer.id} uri={cv.peer.avatar} size={52} />
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

// «Тихо» — спокойный приглушённый зелёный: читается на плитке, но не спорит с активными чатами
const CALM = { dark: '#7CC497', light: '#2F8F5B' };

/** Плитка чата в сетке: иконка, название, активность за сутки. */
function RoomTile({ r, icon, onPress }: { r: Room; icon: IconName; onPress: () => void }) {
  const { c, shadow, dark } = useTheme();
  return (
    <Tap onPress={onPress} scaleTo={0.96} accessibilityLabel={r.title}
      style={{ width: '48.5%', flexDirection: 'row', alignItems: 'center', gap: 10, backgroundColor: c.bgElevated, borderRadius: radius.m,
        borderWidth: HAIRLINE, borderColor: c.line, padding: 14, ...shadow }}>
      <View style={{ width: 32, height: 32, borderRadius: 16, backgroundColor: c.bgSunken, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name={icon} thin size={16} color={c.ink} />
      </View>
      <View style={{ flex: 1, gap: 1 }}>
        <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_600SemiBold' }} numberOfLines={1}>{r.title}</Txt>
        <Txt v="caption" color={r.today ? c.accentText : dark ? CALM.dark : CALM.light} numberOfLines={1}>{r.today ? `${r.today} за сутки` : 'Тихо'}</Txt>
      </View>
    </Tap>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <View style={{ gap: 10 }}>
      <Txt v="headline">{title}</Txt>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'space-between', rowGap: 10 }}>{children}</View>
    </View>
  );
}

function RoomsList({ rooms: all }: { rooms: Room[] }) {
  const { c, shadow } = useTheme();
  const [city] = useCity();
  const country = useCountry();
  // Общие комнаты (для всех стран) и комнаты своей страны
  const common = all.filter((r) => !r.country);
  const rooms = all.filter((r) => r.country === country);
  const mine = rooms.find((r) => r.kind === 'city' && r.title === city);
  const open = (r: Room) => router.push({ pathname: '/room/[slug]', params: { slug: r.slug, title: r.title } });
  const cities = rooms.filter((r) => r.kind === 'city' && r !== mine);
  const topics = rooms.filter((r) => r.kind === 'topic');
  return (
    <View style={{ gap: 22 }}>
      {common.map((r) => (
        <Tap key={r.slug} onPress={() => open(r)} scaleTo={0.98} accessibilityLabel={r.title}
          style={{ flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: c.bgElevated, borderRadius: radius.m,
            borderWidth: HAIRLINE, borderColor: c.line, padding: 14, ...shadow }}>
          <View style={{ width: 40, height: 40, borderRadius: 20, backgroundColor: c.bgSunken, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="globe" thin size={20} color={c.ink} />
          </View>
          <View style={{ flex: 1, gap: 2 }}>
            <Txt v="bodyStrong" numberOfLines={1}>{r.title}</Txt>
            <Txt v="footnote" tone="muted" numberOfLines={1}>{r.today ? `${r.today} сообщ. за сутки` : 'Нидерланды, Германия и Бельгия'}</Txt>
          </View>
          <Icon name="chevron" size={13} color={c.faint} />
        </Tap>
      ))}
      {mine ? (
        <Tap onPress={() => open(mine)} scaleTo={0.98} accessibilityLabel={`Ваш город: ${mine.title}`}
          style={{ flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 9, paddingHorizontal: 12,
            borderRadius: radius.pill, borderWidth: 1, borderColor: c.accent }}>
          <Icon name="location" size={16} color={c.accentText} />
          <Txt v="subhead" tone="ink" style={{ flex: 1 }} numberOfLines={1}>
            <Txt v="subhead" tone="accent">Ваш город · </Txt>
            <Txt v="subhead" tone="ink" style={{ fontFamily: 'Onest_700Bold' }}>{mine.title}</Txt>
          </Txt>
          <Txt v="caption" tone="muted">{mine.today ? `${mine.today} за сутки` : 'Открыть'}</Txt>
          <Icon name="chevron" size={12} color={c.muted} />
        </Tap>
      ) : null}
      {cities.length ? (
        <Section title="Города">{cities.map((r) => <RoomTile key={r.slug} r={r} icon="location" onPress={() => open(r)} />)}</Section>
      ) : null}
      {topics.length ? (
        <Section title="Темы">{topics.map((r) => <RoomTile key={r.slug} r={r} icon="people" onPress={() => open(r)} />)}</Section>
      ) : null}
      <Txt v="footnote" tone="muted" center>Будьте вежливы: у нас есть модерация. Правила — в профиле.</Txt>
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
    <TabScreen title="Сообщения"
      onRefresh={() => Promise.all([rooms.refetch(), ...(user ? [dms.refetch(), friends.refetch()] : [])])}>
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

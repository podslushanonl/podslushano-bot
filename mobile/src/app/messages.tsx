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
import { Badge, Button, Empty, handle, Icon, IconButton, IconName, Img, Skeleton, TabScreen, Tap, Txt, UserAvatar, VerifiedBadge } from '@/ui';
import { Ticks } from '@/features/chat/ChatUI';

/** Строка диалога как в VK: аватар с точкой «в сети», имя с галочкой, время, последнее сообщение со статусом. */
function ConversationRow({ cv }: { cv: Conversation }) {
  const { c } = useTheme();
  const last = cv.last;
  return (
    <Tap onPress={() => router.push({ pathname: '/dm/[id]', params: { id: String(cv.id) } })} scaleTo={0.985}
      accessibilityLabel={`${handle(cv.peer)}${cv.unread ? `, непрочитанных: ${cv.unread}` : ''}`}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 9 }}>
      <View>
        <UserAvatar u={cv.peer} size={56} />
        {cv.peer.online ? <View style={{ position: 'absolute', right: 1, bottom: 1, width: 15, height: 15, borderRadius: 8, backgroundColor: ONLINE,
          borderWidth: 2.5, borderColor: c.bg }} /> : null}
        {cv.listing?.photo ? <Img source={photoUrl(cv.listing)} style={{ position: 'absolute', left: -3, bottom: -3, width: 24, height: 24, borderRadius: 7, borderWidth: 2, borderColor: c.bg }} /> : null}
      </View>
      <View style={{ flex: 1, gap: 3, minWidth: 0 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', minWidth: 0 }}>
            <Txt v="headline" numberOfLines={1} style={{ flexShrink: 1 }}>{handle(cv.peer)}</Txt>
            {cv.peer.verified ? <VerifiedBadge size={15} /> : null}
          </View>
          {last?.mine ? <Ticks status={last.status} color={c.faint} readColor={c.accent} size={13} /> : null}
          {last ? <Txt v="caption" color={cv.unread ? c.accentText : c.faint}>{timeLabel(last.at)}</Txt> : null}
        </View>
        {cv.listing ? <Txt v="caption" tone="accent" numberOfLines={1}>{cv.listing.title}{cv.listing.price ? ` · ${cv.listing.price}` : ''}</Txt> : null}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Txt v="subhead" color={cv.unread ? c.ink : c.muted} numberOfLines={1} style={{ flex: 1, fontFamily: cv.unread ? 'Onest_600SemiBold' : 'Onest_400Regular' }}>
            {last ? `${last.mine ? 'Вы: ' : ''}${last.text}` : 'Новый диалог'}
          </Txt>
          <Badge n={cv.unread} />
        </View>
      </View>
    </Tap>
  );
}

const ONLINE = '#34C759';

/** Вкладки вверху экрана с подчёркиванием (как в VK и Instagram). */
function TopTabs<T extends string>({ items, value, onChange }: { items: { key: T; title: string; badge?: number }[]; value: T; onChange: (k: T) => void }) {
  const { c } = useTheme();
  return (
    <View style={{ flexDirection: 'row', borderBottomWidth: HAIRLINE, borderBottomColor: c.line, marginHorizontal: -20, paddingHorizontal: 12 }}
      accessibilityRole="tablist">
      {items.map((t) => {
        const on = t.key === value;
        return (
          <Tap key={t.key} onPress={() => onChange(t.key)} scaleTo={0.97} haptic="select" accessibilityRole="tab" accessibilityState={{ selected: on }}
            style={{ flex: 1, alignItems: 'center', paddingTop: 6, paddingBottom: 11, borderBottomWidth: 2, borderBottomColor: on ? c.accent : 'transparent', marginBottom: -HAIRLINE }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Txt v="bodyStrong" color={on ? c.ink : c.muted}>{t.title}</Txt>
              {t.badge ? <Badge n={t.badge} /> : null}
            </View>
          </Tap>
        );
      })}
    </View>
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
  const { c } = useTheme();
  const { user } = useAuth();
  // Пока вход не восстановлен, user ещё пуст: вкладку по умолчанию выбираем, когда он известен
  const [picked, setTab] = useState<'dm' | 'rooms' | null>(null);
  const tab = picked ?? (user ? 'dm' : 'rooms');
  const rooms = useRooms();
  const dms = useConversations(!!user);
  const friends = useFriends(!!user);
  const requests = friends.data?.incoming.length || 0;
  return (
    <TabScreen title="Сообщения"
      right={user ? (
        <View>
          <IconButton icon="people" label={requests ? `Друзья, новых заявок: ${requests}` : 'Друзья'} onPress={() => router.push('/friends')} />
          {requests ? <View pointerEvents="none" style={{ position: 'absolute', top: -2, right: -2 }}><Badge n={requests} /></View> : null}
        </View>
      ) : undefined}
      onRefresh={() => Promise.all([rooms.refetch(), ...(user ? [dms.refetch(), friends.refetch()] : [])])}>
      <TopTabs value={tab} onChange={setTab} items={[
        { key: 'dm', title: 'Личные', badge: dms.data?.unread },
        { key: 'rooms', title: 'Общие чаты' },
      ]} />
      {tab === 'rooms' ? (
        rooms.data ? <RoomsList rooms={rooms.data} /> : <View style={{ gap: 10 }}><Skeleton h={120} r={34} /><Skeleton h={260} r={22} /></View>
      ) : !user ? (
        <Empty icon="bubble" title="Личные сообщения" text="Переписывайтесь с друзьями прямо в приложении — без обмена телефонами."
          action={<Button title="Войти" kind="primary" onPress={() => router.push('/login')} />} />
      ) : dms.isLoading ? (
        <View style={{ gap: 14 }}>{[0, 1, 2, 3].map((i) => (
          <View key={i} style={{ flexDirection: 'row', gap: 12, alignItems: 'center' }}><Skeleton w={56} h={56} r={28} /><View style={{ flex: 1, gap: 8 }}><Skeleton w="45%" /><Skeleton w="75%" h={12} /></View></View>
        ))}</View>
      ) : dms.data?.items.length ? (
        <View style={{ marginTop: -6 }}>
          {dms.data.items.map((cv) => <ConversationRow key={cv.id} cv={cv} />)}
          <Txt v="footnote" color={c.faint} center style={{ marginTop: 14 }}>Личные сообщения — для друзей и по объявлениям Барахолки</Txt>
        </View>
      ) : (
        <Empty icon="bubble" title="Пока нет диалогов" text="Добавьте человека в друзья — и пишите друг другу. Найти людей можно по имени или в общих чатах."
          action={<Button title="Найти друзей" kind="secondary" onPress={() => router.push('/friends')} />} />
      )}
    </TabScreen>
  );
}

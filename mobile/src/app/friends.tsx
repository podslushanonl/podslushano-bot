import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { routeForError } from '@/api/community';
import { acceptFriend, addFriend, Person, removeFriend, startChat, unblockPerson, useFriends, useSearchPeople } from '@/api/social';
import { COUNTRIES } from '@/lib/countries';
import { useTheme } from '@/theme';
import { Avatar, Button, ChipRow, Empty, Field, Group, Icon, IconButton, PageScreen, Skeleton, Tap, Txt, useToast } from '@/ui';

function PersonRow({ p, first, right }: { p: Person; first: boolean; right?: React.ReactNode }) {
  const { c } = useTheme();
  return (
    <Tap onPress={() => router.push({ pathname: '/user/[id]', params: { id: String(p.id) } })} scaleTo={0.99}
      style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 12, borderTopWidth: first ? 0 : 1, borderTopColor: c.line }}>
      <Avatar name={p.name} id={p.id} uri={p.avatar} size={46} />
      <View style={{ flex: 1, gap: 2 }}>
        <Txt v="headline" numberOfLines={1}>{p.name}</Txt>
        <Txt v="footnote" numberOfLines={1}>{[p.city, p.country].filter(Boolean).join(', ')}</Txt>
      </View>
      {right}
    </Tap>
  );
}

export default function Friends() {
  const { user, ready } = useAuth();
  const toast = useToast();
  const lists = useFriends(!!user);
  const [q, setQ] = useState('');
  const [debounced, setDebounced] = useState('');
  const [country, setCountry] = useState('');
  const found = useSearchPeople(debounced, country);
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 350); return () => clearTimeout(t); }, [q]);

  const run = (fn: () => Promise<unknown>, ok?: string) => fn().then(() => ok && toast(ok))
    .catch((e: any) => { if (!routeForError(e)) toast(e?.message || 'Не получилось', 'error'); });
  const write = (id: number) => run(async () => {
    const d = await startChat(id);
    router.push({ pathname: '/dm/[id]', params: { id: String(d.id) } });
  });

  if (ready && !user) {
    return (
      <PageScreen title="Друзья">
        <Empty icon="people" title="Друзья" text="Войдите, чтобы находить людей, добавлять в друзья и переписываться."
          action={<Button title="Войти" kind="primary" onPress={() => router.push('/login')} />} />
      </PageScreen>
    );
  }
  const d = lists.data;
  const searching = debounced.trim().length >= 2;
  return (
    <PageScreen title="Друзья" refreshing={lists.isRefetching} onRefresh={() => lists.refetch()}>
      <Txt v="title1">Друзья</Txt>
      <Field value={q} onChangeText={setQ} placeholder="Найти по имени" autoCorrect={false} left={<Icon name="search" size={18} />} />
      <ChipRow value={country} onChange={setCountry}
        items={[{ key: '', title: 'Все страны' }, ...COUNTRIES.map((c) => ({ key: c, title: c }))]} />
      {searching ? (
        found.isLoading ? <Skeleton h={140} r={22} /> : found.data?.length ? (
          <Group title="Найдено">
            {found.data.map((p, i) => (
              <PersonRow key={p.id} p={p} first={i === 0} right={
                p.relation === 'none' ? <Button title="Добавить" kind="accent" size="s" full={false} onPress={() => run(() => addFriend(p.id), 'Заявка отправлена')} />
                  : p.relation === 'friends' ? <IconButton icon="bubble" label="Написать" kind="plain" onPress={() => write(p.id)} />
                  : p.relation === 'incoming' ? <Button title="Принять" kind="accent" size="s" full={false} onPress={() => run(() => acceptFriend(p.id), 'Теперь вы друзья')} />
                  : p.relation === 'outgoing' ? <Txt v="caption">заявка отправлена</Txt> : null} />
            ))}
          </Group>
        ) : <Empty icon="search" title="Никого не нашли" text="Проверьте имя или выберите другую страну." />
      ) : lists.isLoading || !d ? (
        <View style={{ gap: 10 }}><Skeleton h={74} r={22} /><Skeleton h={180} r={22} /></View>
      ) : (
        <>
          {d.incoming.length ? (
            <Group title={`Заявки в друзья · ${d.incoming.length}`}>
              {d.incoming.map((p, i) => (
                <PersonRow key={p.id} p={p} first={i === 0} right={
                  <View style={{ flexDirection: 'row', gap: 6 }}>
                    <Button title="Принять" kind="accent" size="s" full={false} onPress={() => run(() => acceptFriend(p.id), 'Теперь вы друзья')} />
                    <IconButton icon="close" label="Отклонить" kind="plain" onPress={() => run(() => removeFriend(p.id))} />
                  </View>} />
              ))}
            </Group>
          ) : null}
          {d.friends.length ? (
            <Group title={`Друзья · ${d.friends.length}`}>
              {d.friends.map((p, i) => (
                <PersonRow key={p.id} p={p} first={i === 0} right={<IconButton icon="bubble" label={`Написать: ${p.name}`} kind="plain" onPress={() => write(p.id)} />} />
              ))}
            </Group>
          ) : (
            <Empty icon="people" title="Пока нет друзей" text="Найдите знакомых по имени или откройте профиль собеседника в общем чате и добавьте в друзья. Друзьям можно писать в личные сообщения." />
          )}
          {d.outgoing.length ? (
            <Group title="Отправленные заявки">
              {d.outgoing.map((p, i) => (
                <PersonRow key={p.id} p={p} first={i === 0} right={<Button title="Отменить" kind="secondary" size="s" full={false} onPress={() => run(() => removeFriend(p.id))} />} />
              ))}
            </Group>
          ) : null}
          {d.blocked.length ? (
            <Group title="Заблокированные">
              {d.blocked.map((p, i) => (
                <PersonRow key={p.id} p={p} first={i === 0} right={<Button title="Разблокировать" kind="secondary" size="s" full={false} onPress={() => run(() => unblockPerson(p.id))} />} />
              ))}
            </Group>
          ) : null}
        </>
      )}
    </PageScreen>
  );
}

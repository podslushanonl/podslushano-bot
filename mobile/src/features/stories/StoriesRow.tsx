import { router } from 'expo-router';
import { ScrollView, View } from 'react-native';
import { useAuth } from '@/api/auth';
import { useStories } from '@/api/stories';
import { useTheme } from '@/theme';
import { Avatar, Icon, Tap, Txt } from '@/ui';
import { seenStories } from './seen';

const SIZE = 64;

/** Кольцо вокруг аватара: оранжевое — есть непросмотренные истории, серое — всё просмотрено. */
function Ring({ on, children }: { on: boolean; children: React.ReactNode }) {
  const { c } = useTheme();
  return (
    <View style={{ padding: 2.5, borderRadius: (SIZE + 10) / 2, borderWidth: 2.5, borderColor: on ? c.accent : c.lineStrong }}>{children}</View>
  );
}

/** Истории над лентой (как в Instagram): «Ваша история» и кружки друзей и соседей. */
export function StoriesRow() {
  const { c } = useTheme();
  const { user } = useAuth();
  const q = useStories(!!user);
  if (!user) return null;
  const groups = q.data?.groups || [];
  const mine = groups.find((g) => g.mine);
  const others = groups.filter((g) => !g.mine);

  const add = () => router.push('/story-new');
  const open = (uid: number) => router.push({ pathname: '/stories/[uid]', params: { uid: String(uid) } });

  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginHorizontal: -20 }}
      contentContainerStyle={{ paddingHorizontal: 16, gap: 12 }}>
      <View style={{ alignItems: 'center', gap: 6, width: SIZE + 16 }}>
        <Tap onPress={mine ? () => open(user.id) : add} onLongPress={mine ? add : undefined} scaleTo={0.92}
          accessibilityLabel={mine ? 'Ваша история' : 'Добавить историю'} accessibilityHint={mine ? 'Удерживайте, чтобы добавить ещё' : undefined}>
          <Ring on={!!mine}>
            <Avatar name={user.name} id={user.id} uri={user.avatar} size={SIZE} />
          </Ring>
          <Tap onPress={add} scaleTo={0.85} accessibilityLabel="Добавить историю"
            style={{ position: 'absolute', right: 0, bottom: 0, width: 24, height: 24, borderRadius: 12, backgroundColor: c.accent,
              borderWidth: 2.5, borderColor: c.bg, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="plus" size={13} color={c.onAccent} />
          </Tap>
        </Tap>
        <Txt v="caption" tone="ink" numberOfLines={1} style={{ fontSize: 11 }}>Ваша история</Txt>
      </View>
      {others.map((g) => (
        <Tap key={g.user.id} onPress={() => open(g.user.id)} scaleTo={0.92} accessibilityLabel={`История: ${g.user.name}`}
          style={{ alignItems: 'center', gap: 6, width: SIZE + 12 }}>
          <Ring on={g.items.some((s) => !seenStories.has(s.id))}>
            <Avatar name={g.user.name} id={g.user.id} uri={g.user.avatar} size={SIZE} />
          </Ring>
          <Txt v="caption" tone="ink" numberOfLines={1}>{g.user.name.split(' ')[0]}</Txt>
        </Tap>
      ))}
    </ScrollView>
  );
}

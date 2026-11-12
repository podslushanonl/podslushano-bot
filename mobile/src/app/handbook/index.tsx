import { router } from 'expo-router';
import { View } from 'react-native';
import { OTHER, SECTIONS, sectionOf, useHandbook } from '@/api/handbook';
import { openUrl } from '@/lib/open';
import { radius, useTheme } from '@/theme';
import { Button, EmptyState, Group, LargeTitle, PageScreen, Row, Skeleton, Txt } from '@/ui';

/** Короткое название справки для списка: без года и «в Нидерландах». */
function shortTitle(t: string) {
  let s = t.replace(/\s*\(?(в\s+)?20\d\d([–-]20\d\d)?(\s+году)?\)?/g, '').replace(/\s+в Нидерландах/g, '').replace(/\s+:/g, ':').trim();
  const i = s.indexOf(':');
  if (i > 0 && (i >= 20 || /^:\s*пошаг/i.test(s.slice(i)))) s = s.slice(0, i);
  return s.replace(/[:\s]+$/, '');
}

// Экстренные и справочные номера Нидерландов: действуют во всех провинциях.
const NUMBERS: { title: string; sub: string; tel: string }[] = [
  { title: '112', sub: 'Скорая, полиция, пожарные. Когда угрожает жизни', tel: '112' },
  { title: '0900 8844', sub: 'Полиция, если не срочно', tel: '09008844' },
  { title: '113 или 0800 0113', sub: 'Помощь при мыслях о самоубийстве, круглосуточно', tel: '08000113' },
  { title: '0800 2000', sub: 'Veilig Thuis: насилие в семье, жестокое обращение', tel: '08002000' },
];

/** Справочник: экстренные номера, важные даты и пошаговые справки по официальным источникам. */
export default function Handbook() {
  const { c } = useTheme();
  const hb = useHandbook();
  return (
    <PageScreen title="Справочник" refreshing={hb.isRefetching} onRefresh={() => hb.refetch()}>
      <LargeTitle title="Справочник" sub="Документы, здоровье, жильё, работа и налоги по шагам" />
      <Group title="Экстренные номера">
        {NUMBERS.map((n, i) => (
          <Row key={n.tel} first={i === 0} icon="phone" iconBg={i === 0 ? c.danger : undefined} title={n.title} sub={n.sub}
            onPress={() => openUrl(`tel:${n.tel}`)} />
        ))}
      </Group>
      <Group title="Календарь">
        <Row first icon="calendar" title="Важные даты" sub="Праздники, каникулы, сроки налогов и страховки" onPress={() => router.push('/dates')} />
      </Group>
      {hb.isLoading ? <View style={{ gap: 10 }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={56} r={radius.card} />)}</View>
        : hb.isError ? <EmptyState icon="warning" title="Справочник не загрузился" text="Проверьте интернет и попробуйте ещё раз."
          action={<Button kind="secondary" title="Повторить" onPress={() => hb.refetch()} />} />
          : [...SECTIONS, OTHER].map((sec) => {
            const list = (hb.data || []).filter((g) => sectionOf(g.title).key === sec.key);
            if (!list.length) return null;
            return (
              <Group key={sec.key} title={sec.title}>
                {list.map((g, i) => (
                  <Row key={g.id} first={i === 0} icon={sec.icon} title={shortTitle(g.title)}
                    onPress={() => router.push({ pathname: '/handbook/[id]', params: { id: String(g.id) } })} />
                ))}
              </Group>
            );
          })}
      <Txt v="footnote">Справки пишутся по официальным источникам и обновляются, когда меняются правила. Действуют по всей стране.</Txt>
    </PageScreen>
  );
}

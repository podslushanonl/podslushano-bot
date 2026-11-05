import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { catTitle, useSpecialists } from '@/api/guide';
import { OTHER, SECTIONS, sectionOf, useHandbook } from '@/api/handbook';
import { router } from 'expo-router';
import { SpecialistCard } from '@/features/guide/SpecialistCard';
import { HeaderActions, ProvinceSwitch } from '@/features/province/ProvinceSwitch';
import { openUrl } from '@/lib/open';
import { useProvince } from '@/lib/province';
import { radius, useTheme } from '@/theme';
import { Button, ChipRow, Empty, Field, Group, Icon, Row, Segmented, Skeleton, TabScreen, Txt } from '@/ui';

type Part = 'contacts' | 'help';

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

/** «Гид»: контакт-гайд провинции и справочник. */
export default function Guide() {
  const { c } = useTheme();
  const { province } = useProvince();
  const p = province!;
  const q = useSpecialists();
  const hb = useHandbook();
  const [part, setPart] = useState<Part>('contacts');
  const [cat, setCat] = useState('');
  const [text, setText] = useState('');

  // Только специалисты этой провинции и те, кто работает онлайн по всей стране
  const mine = useMemo(() => (q.data || []).filter((s) => s.province === p.name || (s.online && !s.province)), [q.data, p.name]);
  const cats = useMemo(() => {
    const n = new Map<string, number>();
    mine.forEach((s) => n.set(s.category, (n.get(s.category) || 0) + 1));
    return [...n.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  }, [mine]);
  const t = text.trim().toLowerCase();
  const shown = mine
    .filter((s) => (!cat || s.category === cat) && (!t || `${s.name} ${s.category} ${s.description} ${s.city}`.toLowerCase().includes(t)))
    .sort((a, b) => Number(b.premium) - Number(a.premium) || Number(a.online) - Number(b.online));

  return (
    <TabScreen title="Гид" above={<ProvinceSwitch />} right={<HeaderActions />} refreshing={q.isRefetching || hb.isRefetching} onRefresh={() => Promise.all([q.refetch(), hb.refetch()])}>
      <Segmented items={[{ key: 'contacts', title: 'Контакт-гайд' }, { key: 'help', title: 'Справочник' }]} value={part} onChange={setPart} />

      {part === 'contacts' ? (
        <>
          <Field placeholder="Кого ищете: стоматолог, юрист, няня" value={text} onChangeText={setText} returnKeyType="search"
            left={<Icon name="search" size={18} color={c.faint} />} accessibilityLabel="Поиск специалиста" />
          {cats.length > 1 ? (
            <View style={{ marginHorizontal: -20 }}>
              <ChipRow items={[{ key: '', title: 'Все' }, ...cats.map((k) => ({ key: k, title: catTitle(k) }))]} value={cat} onChange={setCat} />
            </View>
          ) : null}
          {q.isLoading ? <View style={{ gap: 10 }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={78} r={radius.l} />)}</View>
            : q.isError && !shown.length ? <Empty icon="warning" title="Контакт-гайд не загрузился" text="Проверьте интернет и попробуйте ещё раз." action={<Button kind="secondary" title="Повторить" onPress={() => q.refetch()} />} />
            : shown.length ? (
              <View style={{ gap: 10 }}>
                <Txt v="footnote">{p.name} и онлайн: {shown.length}</Txt>
                {shown.map((s) => <SpecialistCard key={s.id} s={s} />)}
              </View>
            ) : (
              <Empty icon="people" title="Никого не нашли" text={t || cat ? 'Попробуйте другое слово или категорию.' : `В ${p.name} пока нет специалистов. Загляните в соседнюю провинцию.`}
                action={t || cat ? <Button kind="secondary" title="Сбросить поиск" onPress={() => { setText(''); setCat(''); }} /> : undefined} />
            )}
          <Group title="Для бизнеса">
            <Row first icon="briefcase" title="Добавить свою карточку" sub="Размещение в контакт-гайде оформляется на сайте"
              onPress={() => openUrl('https://www.podslushano.nl/business/')} />
          </Group>
        </>
      ) : (
        <>
          <Group title="Каждый день">
            <Row first icon="newspaper" title="Новости" sub="Главное о Нидерландах на русском" onPress={() => router.push('/news')} />
            <Row icon="calendar" title="Важные даты" sub="Праздники, каникулы, сроки налогов и страховки" onPress={() => router.push('/dates')} />
            <Row icon="briefcase" title="Работа" sub="Вакансии, где пригодится русский" onPress={() => router.push('/jobs')} />
          </Group>
          <Group title="Экстренные номера">
            {NUMBERS.map((n, i) => (
              <Row key={n.tel} first={i === 0} icon="phone" iconBg={i === 0 ? c.danger : undefined} title={n.title} sub={n.sub}
                onPress={() => openUrl(`tel:${n.tel}`)} />
            ))}
          </Group>
          {hb.isLoading ? <View style={{ gap: 10 }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={56} r={radius.l} />)}</View>
            : hb.isError ? <Empty icon="warning" title="Справочник не загрузился" text="Проверьте интернет и попробуйте ещё раз."
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
        </>
      )}
    </TabScreen>
  );
}

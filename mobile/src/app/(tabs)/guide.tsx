import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { catTitle, useSpecialists } from '@/api/guide';
import { SpecialistCard } from '@/features/guide/SpecialistCard';
import { HeaderActions, ProvinceSwitch } from '@/features/province/ProvinceSwitch';
import { openUrl } from '@/lib/open';
import { useProvince } from '@/lib/province';
import { radius, useTheme } from '@/theme';
import { Button, ChipRow, Empty, Field, Group, Icon, Row, Segmented, Skeleton, TabScreen, Txt } from '@/ui';

type Part = 'contacts' | 'help';

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
    <TabScreen title="Гид" above={<ProvinceSwitch />} right={<HeaderActions />} refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
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
        <Group title="Экстренные номера">
          {NUMBERS.map((n, i) => (
            <Row key={n.tel} first={i === 0} icon="phone" iconBg={i === 0 ? c.danger : undefined} title={n.title} sub={n.sub}
              onPress={() => openUrl(`tel:${n.tel}`)} />
          ))}
        </Group>
      )}
    </TabScreen>
  );
}

import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { catTitle, useSpecialists } from '@/api/guide';
import { SpecialistCard } from '@/features/guide/SpecialistCard';
import { ProvinceSwitch } from '@/features/province/ProvinceSwitch';
import { useProvince } from '@/lib/province';
import { HAIRLINE, radius, space, useTheme } from '@/theme';
import { Button, ChipRow, EmptyState, Field, Icon, IconName, Skeleton, TabScreen, Tap, Txt } from '@/ui';

// Быстрые разделы под поиском
const TILES: { icon: IconName; title: string; sub: string; href: '/trains' | '/jobs' | '/save' | '/handbook' }[] = [
  { icon: 'train', title: 'Поезда NS', sub: 'Расписание и сбои', href: '/trains' },
  { icon: 'briefcase', title: 'Работа и жильё', sub: 'Вакансии на русском', href: '/jobs' },
  { icon: 'tag', title: 'Сэкономить', sub: 'Скидки и пособия', href: '/save' },
  { icon: 'guide', title: 'Справочник', sub: 'Документы по шагам', href: '/handbook' },
];
type Where = 'near' | 'online';

/** «Гид»: поиск, полезные сервисы и КонтактGuide — каталог русскоязычных специалистов. */
export default function Guide() {
  const { c } = useTheme();
  const { province: p } = useProvince();
  const q = useSpecialists();
  const [where, setWhere] = useState<Where>('near');
  const [cat, setCat] = useState('');
  const [text, setText] = useState('');

  // «Рядом» — специалисты своей провинции; «Онлайн» — те, кто работает по всей стране
  const mine = useMemo(() => (q.data || []).filter((s) => (where === 'online' ? s.online : s.province === p.name)), [q.data, p.name, where]);
  const cats = useMemo(() => {
    const n = new Map<string, number>();
    mine.forEach((s) => n.set(s.category, (n.get(s.category) || 0) + 1));
    return [...n.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  }, [mine]);
  const t = text.trim().toLowerCase();
  const shown = useMemo(() => mine
    .filter((s) => (!cat || s.category === cat) && (!t || `${s.name} ${s.category} ${s.description} ${s.city}`.toLowerCase().includes(t)))
    .sort((a, b) => Number(b.premium) - Number(a.premium)), [mine, cat, t]);

  return (
    <TabScreen title="Гид" above={<ProvinceSwitch />} refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      <Field placeholder="Кого ищете: стоматолог, юрист, няня" value={text} onChangeText={setText} returnKeyType="search"
        left={<Icon name="search" size={18} color={c.faint} />} accessibilityLabel="Поиск специалиста" />

      {!t ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: space.gap }}>
          {TILES.map((x) => (
            <Tap key={x.href} onPress={() => router.push(x.href)} haptic="light" scaleTo={0.97} accessibilityLabel={`${x.title}. ${x.sub}`}
              style={{ flexBasis: '47%', flexGrow: 1, padding: 14, gap: 10, backgroundColor: c.bgElevated, borderRadius: radius.card,
                borderWidth: HAIRLINE, borderColor: c.line }}>
              <View style={{ width: 40, height: 40, borderRadius: radius.control, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
                <Icon name={x.icon} size={20} color={c.accentText} />
              </View>
              <View style={{ gap: 2 }}>
                <Txt v="headline" numberOfLines={1}>{x.title}</Txt>
                <Txt v="footnote" tone="muted" numberOfLines={1}>{x.sub}</Txt>
              </View>
            </Tap>
          ))}
        </View>
      ) : null}

      <View style={{ gap: space.gap }}>
        <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <Txt v="title2" accessibilityRole="header">КонтактGuide</Txt>
          <Txt v="footnote" tone="muted">{shown.length ? `специалистов: ${shown.length}` : ''}</Txt>
        </View>
        <ChipRow items={[{ key: 'near', title: p.name, icon: 'location' }, { key: 'online', title: 'Онлайн', icon: 'globe' }]}
          value={where} onChange={(k) => { setWhere(k); setCat(''); }} />
        {cats.length > 1 ? <ChipRow items={[{ key: '', title: 'Все' }, ...cats.map((k) => ({ key: k, title: catTitle(k) }))]} value={cat} onChange={setCat} /> : null}
      </View>

      {q.isLoading ? <View style={{ gap: space.gap }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={78} r={radius.card} />)}</View>
        : q.isError && !shown.length ? (
          <EmptyState icon="warning" title="КонтактGuide не загрузился" text="Проверьте интернет и попробуйте ещё раз."
            action={<Button kind="secondary" title="Повторить" onPress={() => q.refetch()} />} />
        ) : shown.length ? shown.map((s) => <SpecialistCard key={s.id} s={s} />) : (
          <EmptyState icon="people" title="Никого не нашли"
            text={t || cat ? 'Попробуйте другое слово или категорию.' : where === 'near' ? `В ${p.name} пока нет специалистов. Посмотрите тех, кто работает онлайн.` : 'Онлайн-специалистов пока нет.'}
            action={t || cat ? <Button kind="secondary" title="Сбросить поиск" onPress={() => { setText(''); setCat(''); }} />
              : where === 'near' ? <Button kind="secondary" icon="globe" title="Показать онлайн" onPress={() => setWhere('online')} /> : undefined} />
        )}

      <Tap onPress={() => router.push({ pathname: '/create/[kind]', params: { kind: 'card' } })} haptic="light" scaleTo={0.99}
        accessibilityLabel="Разместить свою карточку в КонтактGuide за 9,99 евро"
        style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: radius.card, backgroundColor: c.accentSoft }}>
        <Icon name="plus" size={20} color={c.accentText} />
        <View style={{ flex: 1 }}>
          <Txt v="headline">Вы специалист?</Txt>
          <Txt v="footnote" tone="muted">Разместите карточку в КонтактGuide — €9,99</Txt>
        </View>
        <Icon name="chevron" size={14} color={c.accentText} />
      </Tap>
    </TabScreen>
  );
}

import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { SITE } from '@/api/client';
import { useContent } from '@/api/content';
import { JobCard } from '@/features/feed/cards';
import { openUrl } from '@/lib/open';
import { Button, ChipRow, Empty, PageScreen, Skeleton, Txt } from '@/ui';

export default function Jobs() {
  const q = useContent();
  const [city, setCity] = useState('');
  const jobs = useMemo(() => q.data?.jobs || [], [q.data]);
  const cities = useMemo(() => [...new Set(jobs.map((j) => j.city).filter(Boolean) as string[])].sort(), [jobs]);
  const shown = jobs.filter((j) => !city || j.city === city);
  return (
    <PageScreen title="Работа" refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      <View style={{ gap: 6 }}>
        <Txt v="title1">Работа</Txt>
        <Txt v="callout" tone="muted">Вакансии, где нужен русский или подходит английский. Проверяем перед публикацией.</Txt>
      </View>
      {cities.length > 1 ? <ChipRow items={[{ key: '', title: 'Все города' }, ...cities.map((x) => ({ key: x, title: x }))]} value={city} onChange={setCity} /> : null}
      {q.isLoading ? <View style={{ gap: 12 }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={110} r={28} />)}</View>
        : shown.length ? <View style={{ gap: 12 }}>{shown.map((j) => <JobCard key={j.id} j={j} />)}</View>
        : <Empty icon="briefcase" title="Вакансий пока нет" text="Загляните позже." />}
      <Button title="Все вакансии на сайте" kind="secondary" icon="globe" onPress={() => openUrl(`${SITE}/work/`)} />
    </PageScreen>
  );
}

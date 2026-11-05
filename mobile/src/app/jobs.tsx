import { View } from 'react-native';
import { useContent } from '@/api/content';
import { JobCard } from '@/features/daily/JobCard';
import { radius } from '@/theme';
import { Button, Empty, LargeTitle, PageScreen, Skeleton, Txt } from '@/ui';

/** Вакансии, где нужен русский язык или он плюс. Редакция проверяет каждую; отклик — на сайте работодателя. */
export default function Jobs() {
  const q = useContent();
  const jobs = q.data?.jobs || [];
  return (
    <PageScreen title="Работа" refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      <LargeTitle title="Работа" sub="Вакансии в Нидерландах, где пригодится русский язык" />
      {q.isLoading ? <View style={{ gap: 12 }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={120} r={radius.l} />)}</View>
        : jobs.length ? jobs.map((j) => <JobCard key={j.id} j={j} />)
          : <Empty icon="briefcase" title={q.isError ? 'Вакансии не загрузились' : 'Новых вакансий пока нет'}
            text={q.isError ? 'Проверьте интернет и попробуйте ещё раз.' : 'Редакция добавляет вакансии каждую неделю.'}
            action={q.isError ? <Button kind="secondary" title="Повторить" onPress={() => q.refetch()} /> : undefined} />}
      <Txt v="footnote">Отклик — на сайте работодателя. podslushano.nl не берёт денег с соискателей.</Txt>
    </PageScreen>
  );
}

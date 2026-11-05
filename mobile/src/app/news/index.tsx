import { useMemo } from 'react';
import { View } from 'react-native';
import { newsProvince } from '@/api/daily';
import { useContent } from '@/api/content';
import { NewsRow } from '@/features/news/NewsRow';
import { useProvince } from '@/lib/province';
import { radius, useTheme } from '@/theme';
import { Button, Empty, LargeTitle, PageScreen, Skeleton } from '@/ui';

/** Все новости Нидерландов на русском (редакция podslushano.nl). Новости своей провинции отмечены. */
export default function NewsList() {
  const { c } = useTheme();
  const q = useContent();
  const { province } = useProvince();
  const news = useMemo(() => (q.data?.news || []).map((n) => ({ n, local: !!province && newsProvince(n.h) === province.id })), [q.data, province]);
  return (
    <PageScreen title="Новости" refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      <LargeTitle title="Новости" sub="Главное о жизни в Нидерландах — на русском, каждый день" />
      {q.isLoading ? <View style={{ gap: 14 }}>{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} h={64} r={radius.m} />)}</View>
        : q.isError && !news.length ? <Empty icon="warning" title="Новости не загрузились" text="Проверьте интернет и попробуйте ещё раз."
          action={<Button kind="secondary" title="Повторить" onPress={() => q.refetch()} />} />
          : (
            <View style={{ gap: 16 }}>
              {news.map(({ n, local }, i) => (
                <View key={n.id} style={{ gap: 16 }}>
                  {i ? <View style={{ height: 1, backgroundColor: c.line }} /> : null}
                  <NewsRow n={n} local={local} />
                </View>
              ))}
            </View>
          )}
    </PageScreen>
  );
}

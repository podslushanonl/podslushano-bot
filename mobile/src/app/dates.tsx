import { useMemo } from 'react';
import { View } from 'react-native';
import { NlDate, schoolRegion, useNlDates } from '@/api/daily';
import { monthTitle } from '@/lib/format';
import { DateCard } from '@/features/daily/DateCard';
import { useProvince } from '@/lib/province';
import { radius } from '@/theme';
import { Button, Empty, LargeTitle, PageScreen, Skeleton, Txt } from '@/ui';

/** Когда, что и почему: праздники, каникулы в вашем регионе, перевод часов, сроки налогов и страховки. */
export default function Dates() {
  const { province } = useProvince();
  const q = useNlDates(province?.id);
  const groups = useMemo(() => {
    const m = new Map<string, NlDate[]>();
    for (const d of q.data || []) { const k = d.date.slice(0, 7); m.set(k, [...(m.get(k) || []), d]); }
    return [...m.entries()];
  }, [q.data]);
  const region = province ? schoolRegion(province.id) : null;
  return (
    <PageScreen title="Важные даты" refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      <LargeTitle title="Важные даты" sub={region ? `Праздники, сроки и школьные каникулы — регион ${region} (${province!.name})` : 'Праздники, сроки и школьные каникулы'} />
      {q.isLoading ? <View style={{ gap: 12 }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={72} r={radius.l} />)}</View>
        : q.isError ? <Empty icon="warning" title="Даты не загрузились" text="Проверьте интернет и попробуйте ещё раз."
          action={<Button kind="secondary" title="Повторить" onPress={() => q.refetch()} />} />
          : groups.map(([month, rows]) => (
            <View key={month} style={{ gap: 10 }}>
              <Txt v="title2" accessibilityRole="header">{monthTitle(`${month}-01`)}</Txt>
              {rows.map((d) => <DateCard key={d.date + d.title} d={d} />)}
            </View>
          ))}
    </PageScreen>
  );
}

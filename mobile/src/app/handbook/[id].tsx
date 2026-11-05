import { useLocalSearchParams } from 'expo-router';
import { Share, View } from 'react-native';
import { useArticle } from '@/api/handbook';
import { ArticleBlock } from '@/features/handbook/Blocks';
import { radius } from '@/theme';
import { Button, Empty, IconButton, PageScreen, Skeleton, Txt } from '@/ui';

/** Статья справочника: нативный показ справки с сайта. */
export default function HandbookArticle() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const q = useArticle(Number(id));
  const a = q.data;
  return (
    <PageScreen title={a?.title || ''} refreshing={q.isRefetching} onRefresh={() => q.refetch()}
      right={a ? <IconButton icon="share" label="Поделиться" onPress={() => Share.share({ message: `${a.title}\n${a.link}` })} /> : undefined}>
      {q.isLoading ? (
        <View style={{ gap: 14 }}>
          <Skeleton h={34} w="80%" /><Skeleton h={160} r={radius.l} /><Skeleton h={16} /><Skeleton h={16} /><Skeleton h={16} w="60%" />
        </View>
      ) : q.isError || !a ? (
        <Empty icon="warning" title="Не получилось загрузить статью" text="Проверьте интернет и попробуйте ещё раз."
          action={<Button kind="secondary" title="Повторить" onPress={() => q.refetch()} />} />
      ) : (
        <>
          <Txt v="title1" accessibilityRole="header">{a.title}</Txt>
          {a.blocks.map((b, i) => <ArticleBlock key={i} b={b} />)}
          <Txt v="footnote">Справка носит информационный характер. Правила меняются: перед подачей документов сверяйтесь с официальным сайтом.</Txt>
        </>
      )}
    </PageScreen>
  );
}

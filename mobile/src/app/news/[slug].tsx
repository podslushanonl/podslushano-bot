import { useLocalSearchParams } from 'expo-router';
import { Share, View } from 'react-native';
import { useNewsArticle } from '@/api/daily';
import { ArticleBlock } from '@/features/handbook/Blocks';
import { ago } from '@/lib/format';
import { openUrl } from '@/lib/open';
import { radius } from '@/theme';
import { Button, Empty, IconButton, Img, PageScreen, Skeleton, Txt } from '@/ui';

/** Новость целиком внутри приложения. */
export default function NewsArticle() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const q = useNewsArticle(String(slug || ''));
  const a = q.data;
  return (
    <PageScreen title={a?.title || 'Новость'} refreshing={q.isRefetching} onRefresh={() => q.refetch()}
      right={a ? <IconButton icon="share" label="Поделиться" onPress={() => Share.share({ message: `${a.title}\n${a.link}` })} /> : undefined}>
      {q.isLoading ? (
        <View style={{ gap: 14 }}><Skeleton h={200} r={radius.l} /><Skeleton h={30} w="85%" /><Skeleton h={16} /><Skeleton h={16} /><Skeleton h={16} w="60%" /></View>
      ) : q.isError || !a ? (
        <Empty icon="warning" title="Не получилось загрузить новость" text="Проверьте интернет и попробуйте ещё раз."
          action={<Button kind="secondary" title="Повторить" onPress={() => q.refetch()} />} />
      ) : (
        <>
          {a.img ? <Img source={a.img} style={{ width: '100%', aspectRatio: 16 / 9, borderRadius: radius.l }} accessibilityIgnoresInvertColors /> : null}
          <View style={{ gap: 6 }}>
            <Txt v="footnote" tone="muted">{ago(a.date.slice(0, 10), a.date.slice(11, 16))}</Txt>
            <Txt v="title1" accessibilityRole="header">{a.title}</Txt>
          </View>
          {a.blocks.map((b, i) => <ArticleBlock key={i} b={b} />)}
          <Button kind="secondary" icon="globe" title="Открыть на сайте" onPress={() => openUrl(a.link)} />
        </>
      )}
    </PageScreen>
  );
}

import { router } from 'expo-router';
import { View } from 'react-native';
import { useAuth } from '@/api/auth';
import { CAT_ICON, photoUrl, useMyListings } from '@/api/market';
import { radius, useTheme } from '@/theme';
import { Button, Empty, Icon, Img, PageScreen, Skeleton, Tap, Txt } from '@/ui';

export default function MyListings() {
  const { c } = useTheme();
  const { user } = useAuth();
  const q = useMyListings(!!user);
  const color = (s?: string) => ({ approved: c.success, pending: c.info, awaiting_payment: c.accentText, rejected: c.danger }[s || ''] || c.muted);
  return (
    <PageScreen title="Мои объявления" refreshing={q.isRefetching} onRefresh={() => q.refetch()}
      footer={<Button title="Подать объявление" icon="plus" kind="primary" onPress={() => router.push('/market/new')} />}>
      <View style={{ gap: 6 }}>
        <Txt v="title1">Мои объявления</Txt>
        <Txt v="callout" tone="muted">До {q.data?.max ?? 5} активных одновременно. Публикация — на 30 дней после проверки.</Txt>
      </View>
      {q.isLoading ? <View style={{ gap: 10 }}>{[0, 1, 2].map((i) => <Skeleton key={i} h={88} r={22} />)}</View>
        : !q.data?.items.length ? <Empty icon="market" title="Пока нет объявлений" text="Продайте ненужное или отдайте даром — это бесплатно." />
        : (
          <View style={{ gap: 10 }}>
            {q.data.items.map((l) => (
              <Tap key={l.id} onPress={() => router.push({ pathname: '/market/[id]', params: { id: String(l.id) } })} scaleTo={0.98}
                style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 10, borderRadius: radius.l, backgroundColor: c.bgElevated, borderWidth: 1, borderColor: c.line }}>
                {l.photo ? <Img source={photoUrl(l)} style={{ width: 68, height: 68, borderRadius: 16 }} />
                  : <View style={{ width: 68, height: 68, borderRadius: 16, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
                      <Icon name={CAT_ICON[l.cat] || 'box'} color={c.accentText} /></View>}
                <View style={{ flex: 1, gap: 4 }}>
                  <Txt v="bodyStrong" numberOfLines={2}>{l.title}</Txt>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                    <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: color(l.status) }} />
                    <Txt v="footnote" color={color(l.status)} style={{ fontFamily: 'Onest_700Bold' }}>{l.status_title}</Txt>
                    {l.price ? <Txt v="footnote">· {l.price}</Txt> : null}
                  </View>
                </View>
                <Icon name="chevron" size={14} color={c.faint} />
              </Tap>
            ))}
          </View>
        )}
    </PageScreen>
  );
}

import { router } from 'expo-router';
import { View } from 'react-native';
import { euro, useCart, useCatalog, useMyOrders, useOrder } from '@/api/shop';
import { radius, useTheme } from '@/theme';
import { Card, Group, Icon, IconButton, Img, Row, Skeleton, TabScreen, Tap, Txt } from '@/ui';

/** Строка «мой заказ»: номер и статус подгружаются с сервера. */
function MyOrder({ token, first }: { token: string; first: boolean }) {
  const q = useOrder(token);
  if (!q.data) return null;
  return <Row first={first} icon="box" title={`Заказ ${q.data.code}`} sub={`${q.data.status_ru} · ${euro(q.data.total)}`}
    onPress={() => router.push({ pathname: '/shop/order/[token]', params: { token } })} />;
}

/** «Магазин»: мерч podslushano.nl. Общий для всех провинций. */
export default function Shop() {
  const { c } = useTheme();
  const q = useCatalog();
  const cart = useCart();
  const orders = useMyOrders();
  const count = cart.reduce((n, l) => n + l.qty, 0);
  const goods = (q.data?.products || []).filter((p) => p.available);
  const open = !!q.data?.open && goods.length > 0;

  const cartButton = open ? (
    <View>
      <IconButton icon="market" label={count ? `Корзина, товаров: ${count}` : 'Корзина'} onPress={() => router.push('/cart')} />
      {count ? (
        <View pointerEvents="none" style={{ position: 'absolute', top: -2, right: -2, minWidth: 20, height: 20, borderRadius: 10, paddingHorizontal: 5,
          backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center' }}>
          <Txt v="caption" color={c.onAccent} style={{ fontFamily: 'Onest_700Bold' }}>{count}</Txt>
        </View>
      ) : null}
    </View>
  ) : undefined;

  return (
    <TabScreen title="Магазин" sub="Мерч podslushano.nl" right={cartButton} refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      {q.isLoading ? (
        <View style={{ flexDirection: 'row', gap: 12 }}><Skeleton w="48%" h={260} r={radius.l} /><Skeleton w="48%" h={260} r={radius.l} /></View>
      ) : open ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
          {goods.map((p) => (
            <Tap key={p.id} onPress={() => router.push({ pathname: '/shop/[id]', params: { id: p.id } })} scaleTo={0.97}
              accessibilityLabel={`${p.title}, ${euro(p.price)}`}
              style={{ width: '48%', flexGrow: 1, backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: 1, borderColor: c.line, overflow: 'hidden' }}>
              {p.images?.[0] ? <Img source={p.images[0]} style={{ width: '100%', aspectRatio: 4 / 5, backgroundColor: c.placeholder }} />
                : <View style={{ width: '100%', aspectRatio: 4 / 5, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
                  <Icon name="market" size={36} color={c.accentText} /></View>}
              <View style={{ padding: 12, gap: 4 }}>
                <Txt v="headline" numberOfLines={2}>{p.title}</Txt>
                <Txt v="callout" tone="accent" style={{ fontFamily: 'Onest_700Bold' }}>{euro(p.price)}</Txt>
              </View>
            </Tap>
          ))}
        </View>
      ) : (
        <>
          <Card pad={20} style={{ borderRadius: radius.xl, gap: 14, backgroundColor: c.accentSoft, borderColor: c.accentSoft }}>
            <View style={{ width: 56, height: 56, borderRadius: radius.m, backgroundColor: c.bgElevated, alignItems: 'center', justifyContent: 'center' }}>
              <Icon name="market" size={28} color={c.accentText} />
            </View>
            <Txt v="title2">Шопперы podslushano.nl</Txt>
            <Txt v="body">Готовим первую коллекцию. Каждый шоппер печатается под ваш заказ и приходит по почте.</Txt>
          </Card>
          <Group title="Как это будет">
            <Row first icon="creditcard" title="Оплата в приложении" sub="iDEAL, Bancontact, карта" chevron={false} />
            <Row icon="box" title="Доставка" sub="Нидерланды, Германия и Бельгия" chevron={false} />
            <Row icon="repost" title="Возврат" sub="14 дней на отказ от заказа" chevron={false} />
          </Group>
        </>
      )}
      {orders.length ? <Group title="Мои заказы">{orders.map((t, i) => <MyOrder key={t} token={t} first={i === 0} />)}</Group> : null}
    </TabScreen>
  );
}

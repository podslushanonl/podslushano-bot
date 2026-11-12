import { router } from 'expo-router';
import { View } from 'react-native';
import { euro, useCart, useCatalog, useMyOrders, useOrder, useWaitlist } from '@/api/shop';
import { radius, useTheme } from '@/theme';
import { Button, Card, Empty, Group, Icon, IconButton, Img, Row, Skeleton, TabScreen, Tap, Txt } from '@/ui';

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
  const wl = useWaitlist();

  const cartButton = open ? (
    <View>
      <IconButton icon="market" label={count ? `Корзина, товаров: ${count}` : 'Корзина'} onPress={() => router.push('/cart')} />
      {count ? (
        <View pointerEvents="none" style={{ position: 'absolute', top: -2, right: -2, minWidth: 20, height: 20, borderRadius: 10, paddingHorizontal: 5,
          backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center' }}>
          <Txt v="caption" color={c.onAccent} style={{ fontWeight: '700' }}>{count}</Txt>
        </View>
      ) : null}
    </View>
  ) : undefined;

  return (
    <TabScreen title="Магазин" sub="Шопперы ALLO" right={cartButton} refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      {q.isLoading ? (
        <View style={{ flexDirection: 'row', gap: 12 }}><Skeleton w="48%" h={260} r={radius.l} /><Skeleton w="48%" h={260} r={radius.l} /></View>
      ) : goods.length ? (
        <>
          {!open ? (
            <Card pad={18} style={{ borderRadius: radius.l, gap: 6, backgroundColor: c.accentSoft, borderColor: c.accentSoft }}>
              <Txt v="headline">Скоро в продаже</Txt>
              <Txt v="callout" tone="text">
                Шопперы ALLO печатаются под заказ. Выберите дизайн и запишитесь в лист ожидания: напишем первыми, когда откроем продажи.
              </Txt>
              {wl.data ? <Txt v="footnote">Уже в листе ожидания: {wl.data}</Txt> : null}
            </Card>
          ) : null}
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
            {goods.map((p) => (
              <Tap key={p.id} onPress={() => router.push({ pathname: '/shop/[id]', params: { id: p.id } })} scaleTo={0.97}
                accessibilityLabel={`${p.title}, ${euro(p.price)}`}
                style={{ width: '47%', flexGrow: 1, backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: 1, borderColor: c.line, overflow: 'hidden' }}>
                {p.images?.[0] ? <Img source={p.images[0]} style={{ width: '100%', aspectRatio: 4 / 5, backgroundColor: c.placeholder }} />
                  : <View style={{ width: '100%', aspectRatio: 4 / 5, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
                    <Icon name="market" size={36} color={c.accentText} /></View>}
                <View style={{ padding: 12, gap: 4 }}>
                  <Txt v="subhead" tone="ink" numberOfLines={2} style={{ fontWeight: '600', minHeight: 38 }}>{p.title.replace(/^Шоппер ALLO /, '')}</Txt>
                  <Txt v="callout" tone="accent" style={{ fontWeight: '700' }}>{euro(p.price)}</Txt>
                </View>
              </Tap>
            ))}
          </View>
        </>
      ) : (
        q.isError ? <Empty icon="warning" title="Магазин не загрузился" text="Проверьте интернет и попробуйте ещё раз." action={<Button kind="secondary" title="Повторить" onPress={() => q.refetch()} />} />
          : <Empty icon="market" title="Товаров пока нет" text="Скоро здесь появится мерч." />
      )}
      {orders.length ? <Group title="Мои заказы">{orders.map((t, i) => <MyOrder key={t} token={t} first={i === 0} />)}</Group> : null}
    </TabScreen>
  );
}

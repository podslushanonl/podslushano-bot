import { router } from 'expo-router';
import { View } from 'react-native';
import { euro, setQty, useCart, useCatalog } from '@/api/shop';
import { radius, useTheme } from '@/theme';
import { Button, Empty, IconButton, Img, PageScreen, Txt } from '@/ui';

/** Корзина: товары, количество, сумма без доставки. Хранится на телефоне. */
export default function Cart() {
  const { c } = useTheme();
  const cart = useCart();
  const cat = useCatalog();
  const lines = cart.map((l) => ({ ...l, p: cat.data?.products.find((p) => p.id === l.id && p.available) })).filter((l) => l.p);
  const subtotal = lines.reduce((s, l) => s + Number(l.p!.price) * l.qty, 0);

  return (
    <PageScreen title="Корзина"
      footer={lines.length && cat.data?.open ? <Button kind="accent" title={`Оформить заказ · ${euro(subtotal)}`} onPress={() => router.push('/checkout')} /> : undefined}>
      <Txt v="title1" accessibilityRole="header">Корзина</Txt>
      {!lines.length ? (
        <Empty icon="market" title="Корзина пуста" text="Загляните в магазин: шопперы печатаются под каждый заказ."
          action={<Button kind="secondary" title="В магазин" onPress={() => router.replace('/shop')} />} />
      ) : (
        <>
          {lines.map((l) => (
            <View key={l.id + l.color} style={{ flexDirection: 'row', gap: 12, alignItems: 'center', backgroundColor: c.bgElevated, borderRadius: radius.l,
              borderWidth: 1, borderColor: c.line, padding: 12 }}>
              {l.p!.images?.[0] ? <Img source={l.p!.images[0]} style={{ width: 64, height: 80, borderRadius: radius.s }} /> : null}
              <View style={{ flex: 1, gap: 2 }}>
                <Txt v="headline" numberOfLines={2}>{l.p!.title}</Txt>
                {l.color ? <Txt v="footnote">{l.color}</Txt> : null}
                <Txt v="callout" tone="accent" style={{ fontFamily: 'Onest_700Bold' }}>{euro(Number(l.p!.price) * l.qty)}</Txt>
              </View>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                <IconButton icon={l.qty === 1 ? 'trash' : 'minus'} kind="plain" size={38} label={l.qty === 1 ? 'Убрать из корзины' : 'Меньше'}
                  onPress={() => setQty(l.id, l.color, l.qty - 1)} />
                <Txt v="headline" style={{ minWidth: 18, textAlign: 'center' }}>{l.qty}</Txt>
                <IconButton icon="plus" kind="plain" size={38} label="Больше" onPress={() => setQty(l.id, l.color, l.qty + 1)} />
              </View>
            </View>
          ))}
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <Txt v="bodyStrong">Товары</Txt>
            <Txt v="bodyStrong">{euro(subtotal)}</Txt>
          </View>
          <Txt v="footnote">Стоимость доставки зависит от страны и появится на следующем шаге.</Txt>
        </>
      )}
    </PageScreen>
  );
}

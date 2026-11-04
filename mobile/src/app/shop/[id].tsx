import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, useWindowDimensions, View } from 'react-native';
import { addToCart, euro, useCatalog } from '@/api/shop';
import { radius, useTheme } from '@/theme';
import { Button, ChipRow, Empty, IconButton, Img, PageScreen, Skeleton, Txt, useToast } from '@/ui';

/** Товар: фото (листаются), цена, цвет, количество, «В корзину». */
export default function ProductScreen() {
  const { c } = useTheme();
  const toast = useToast();
  const { width } = useWindowDimensions();
  const { id } = useLocalSearchParams<{ id: string }>();
  const q = useCatalog();
  const p = q.data?.products.find((x) => x.id === id);
  const [color, setColor] = useState('');
  const [qty, setQty] = useState(1);

  if (q.isLoading) return <PageScreen title=""><Skeleton h={420} r={radius.xl} /></PageScreen>;
  if (!p || !p.available) return <PageScreen title=""><Empty icon="market" title="Товара нет в продаже" /></PageScreen>;
  const colors = p.colors || [];
  const picked = colors.length ? color || colors[0] : '';
  const w = Math.min(width, 520) - 40;

  return (
    <PageScreen title={p.title} footer={
      <Button kind="accent" icon="market" title={`В корзину · ${euro(Number(p.price) * qty)}`}
        onPress={() => { addToCart(p.id, picked, qty); toast('Добавлено в корзину'); router.push('/cart'); }} />
    }>
      {p.images?.length ? (
        <ScrollView horizontal pagingEnabled showsHorizontalScrollIndicator={false} style={{ borderRadius: radius.xl }}>
          {p.images.map((src) => <Img key={src} source={src} style={{ width: w, aspectRatio: 4 / 5, backgroundColor: c.placeholder }} />)}
        </ScrollView>
      ) : null}
      <View style={{ gap: 6 }}>
        <Txt v="title1" accessibilityRole="header">{p.title}</Txt>
        <Txt v="title2" tone="accent">{euro(p.price)}</Txt>
      </View>
      {p.text ? <Txt v="body">{p.text}</Txt> : null}
      {colors.length > 1 ? (
        <View style={{ gap: 8 }}>
          <Txt v="overline">Цвет</Txt>
          <View style={{ marginHorizontal: -20 }}><ChipRow items={colors.map((x) => ({ key: x, title: x }))} value={picked} onChange={setColor} /></View>
        </View>
      ) : null}
      <View style={{ gap: 8 }}>
        <Txt v="overline">Количество</Txt>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
          <IconButton icon="minus" kind="plain" label="Меньше" onPress={() => setQty(Math.max(1, qty - 1))} />
          <Txt v="title2" style={{ minWidth: 24, textAlign: 'center' }} accessibilityLiveRegion="polite">{qty}</Txt>
          <IconButton icon="plus" kind="plain" label="Больше" onPress={() => setQty(Math.min(10, qty + 1))} />
        </View>
      </View>
      <Txt v="footnote">Печатаем под ваш заказ и отправляем в течение 5 рабочих дней. Вернуть товар можно в течение 14 дней после получения.</Txt>
    </PageScreen>
  );
}

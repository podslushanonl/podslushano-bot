import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { ScrollView, useWindowDimensions, View } from 'react-native';
import { useAuth } from '@/api/auth';
import { ApiError } from '@/api/client';
import { addToCart, euro, joinWaitlist, useCatalog, useWaitlist } from '@/api/shop';
import { radius, useTheme } from '@/theme';
import { Button, ChipRow, Empty, Field, Icon, IconButton, Img, PageScreen, Skeleton, Tap, Txt, useToast } from '@/ui';

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
  const { user } = useAuth();
  const wl = useWaitlist();
  const [email, setEmail] = useState(user?.email || '');
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [joined, setJoined] = useState<number | null>(null);

  if (q.isLoading) return <PageScreen title=""><Skeleton h={420} r={radius.xl} /></PageScreen>;
  if (!p || !p.available) return <PageScreen title=""><Empty icon="market" title="Товара нет в продаже" /></PageScreen>;
  const colors = p.colors || [];
  const picked = colors.length ? color || colors[0] : '';
  const w = Math.min(width, 520) - 40;

  return (
    <PageScreen title={p.title} footer={q.data?.open ? (
      <Button kind="accent" icon="market" title={`В корзину · ${euro(Number(p.price) * qty)}`}
        onPress={() => { addToCart(p.id, picked, qty); toast('Добавлено в корзину'); router.push('/cart'); }} />
    ) : undefined}>
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
      {q.data?.open ? (
      <View style={{ gap: 8 }}>
          <Txt v="overline">Количество</Txt>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
            <IconButton icon="minus" kind="plain" label="Меньше" onPress={() => setQty(Math.max(1, qty - 1))} />
            <Txt v="title2" style={{ minWidth: 24, textAlign: 'center' }} accessibilityLiveRegion="polite">{qty}</Txt>
            <IconButton icon="plus" kind="plain" label="Больше" onPress={() => setQty(Math.min(10, qty + 1))} />
          </View>
        </View>
      ) : joined ? (
        <View style={{ gap: 8, backgroundColor: c.accentSoft, borderRadius: radius.l, padding: 16 }}>
          <Icon name="check" size={22} color={c.accentText} />
          <Txt v="headline">Вы в листе ожидания, номер {joined}</Txt>
          <Txt v="callout" tone="text">Напишем на {email.trim()}, когда откроем продажи. Письмо-подтверждение уже отправили.</Txt>
        </View>
      ) : (
        <View style={{ gap: 12 }}>
          <Txt v="headline">Скоро в продаже</Txt>
          <Txt v="callout" tone="muted">Запишитесь в лист ожидания: в день старта продаж напишем вам первыми.{wl.data ? ` Уже записались: ${wl.data}.` : ''}</Txt>
          <Field label="Почта" value={email} onChangeText={setEmail} keyboardType="email-address" autoCapitalize="none"
            autoComplete="email" textContentType="emailAddress" placeholder="you@example.com" />
          <Tap onPress={() => setConsent(!consent)} accessibilityRole="checkbox" accessibilityState={{ checked: consent }}
            style={{ flexDirection: 'row', gap: 10, alignItems: 'flex-start' }}>
            <View style={{ width: 24, height: 24, borderRadius: 7, borderWidth: 2, borderColor: consent ? c.accent : c.lineStrong,
              backgroundColor: consent ? c.accent : 'transparent', alignItems: 'center', justifyContent: 'center', marginTop: 1 }}>
              {consent ? <Icon name="check" size={14} color={c.onAccent} /> : null}
            </View>
            <Txt v="subhead" tone="text" style={{ flex: 1 }}>Согласен получить письмо о старте продаж. Отписаться можно в один клик.</Txt>
          </Tap>
          <Button kind="accent" icon="bell" title="Записаться в лист ожидания" loading={busy} disabled={!consent || !email.trim()}
            onPress={async () => {
              setBusy(true);
              try {
                const r = await joinWaitlist(email, p.id);
                setJoined(r.position);
                wl.refetch();
              } catch (e) {
                toast(e instanceof ApiError ? e.message : 'Не получилось записаться. Попробуйте ещё раз.', 'error');
              } finally { setBusy(false); }
            }} />
        </View>
      )}
      <Txt v="footnote">Печатаем под ваш заказ и отправляем в течение 5 рабочих дней. Вернуть товар можно в течение 14 дней после получения.</Txt>
    </PageScreen>
  );
}

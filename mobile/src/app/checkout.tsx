import * as WebBrowser from 'expo-web-browser';
import { router } from 'expo-router';
import { useState } from 'react';
import { Platform, View } from 'react-native';
import { useAuth } from '@/api/auth';
import { ApiError } from '@/api/client';
import { Address, clearCart, Country, createOrder, euro, useCart, useCatalog } from '@/api/shop';
import { useTheme } from '@/theme';
import { Button, Field, Group, PageScreen, Row, Segmented, Txt, useToast } from '@/ui';

const PLACEHOLDER: Record<Country, string> = { NL: '1011 AB', DE: '10115', BE: '1000' };

/** Оформление: страна доставки, получатель, адрес, итог и переход к оплате Mollie. */
export default function Checkout() {
  const { c } = useTheme();
  const toast = useToast();
  const { user } = useAuth();
  const cart = useCart();
  const cat = useCatalog();
  const [a, setA] = useState<Address>({ country: 'NL', name: user?.name || '', email: user?.email || '', phone: user?.phone || '',
    street: '', house: '', postcode: '', city: '' });
  const [busy, setBusy] = useState(false);
  const set = (k: keyof Address) => (v: string) => setA((x) => ({ ...x, [k]: v }));

  const lines = cart.map((l) => ({ ...l, p: cat.data?.products.find((p) => p.id === l.id && p.available) })).filter((l) => l.p);
  const subtotal = lines.reduce((s, l) => s + Number(l.p!.price) * l.qty, 0);
  const shipping = Number(cat.data?.shipping[a.country] || 0);

  const pay = async () => {
    setBusy(true);
    try {
      const d = await createOrder(lines, a);
      clearCart();
      if (Platform.OS === 'web') (globalThis as any).location.href = d.checkout_url;
      else {
        await WebBrowser.openBrowserAsync(d.checkout_url, { presentationStyle: WebBrowser.WebBrowserPresentationStyle.PAGE_SHEET });
        router.replace({ pathname: '/shop/order/[token]', params: { token: d.token } });
      }
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Не получилось оформить заказ. Попробуйте ещё раз.', 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <PageScreen title="Оформление" footer={<Button kind="accent" icon="creditcard" title={`Оплатить ${euro(subtotal + shipping)}`} loading={busy} onPress={pay} />}>
      <Txt v="title1" accessibilityRole="header">Оформление</Txt>
      <View style={{ gap: 8 }}>
        <Txt v="overline">Страна доставки</Txt>
        <Segmented items={[{ key: 'NL', title: 'Нидерланды' }, { key: 'DE', title: 'Германия' }, { key: 'BE', title: 'Бельгия' }]}
          value={a.country} onChange={(v) => setA((x) => ({ ...x, country: v as Country }))} />
      </View>
      <Field label="Имя и фамилия" value={a.name} onChangeText={set('name')} autoComplete="name" textContentType="name" />
      <Field label="Почта" hint="Пришлём подтверждение и ссылку на отслеживание" value={a.email} onChangeText={set('email')}
        keyboardType="email-address" autoCapitalize="none" autoComplete="email" textContentType="emailAddress" />
      <Field label="Телефон, необязательно" hint="Номер Нидерландов, Германии или Бельгии — для курьера" value={a.phone} onChangeText={set('phone')}
        keyboardType="phone-pad" autoComplete="tel" textContentType="telephoneNumber" />
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <View style={{ flex: 3 }}><Field label="Улица" value={a.street} onChangeText={set('street')} autoComplete="street-address" textContentType="streetAddressLine1" /></View>
        <View style={{ flex: 1.3 }}><Field label="Дом" value={a.house} onChangeText={set('house')} /></View>
      </View>
      <View style={{ flexDirection: 'row', gap: 10 }}>
        <View style={{ flex: 1.3 }}><Field label="Индекс" placeholder={PLACEHOLDER[a.country]} value={a.postcode} onChangeText={set('postcode')}
          autoCapitalize="characters" autoComplete="postal-code" textContentType="postalCode" /></View>
        <View style={{ flex: 2 }}><Field label="Город" value={a.city} onChangeText={set('city')} textContentType="addressCity" /></View>
      </View>
      <Group title="Итого">
        {lines.map((l, i) => <Row key={l.id + l.color} first={i === 0} title={`${l.p!.title} × ${l.qty}`} sub={l.color || undefined}
          right={<Txt v="bodyStrong">{euro(Number(l.p!.price) * l.qty)}</Txt>} chevron={false} />)}
        <Row title="Доставка" sub={cat.data?.countries[a.country]} right={<Txt v="bodyStrong">{euro(shipping)}</Txt>} chevron={false} />
        <Row title="К оплате" right={<Txt v="bodyStrong" color={c.accentText}>{euro(subtotal + shipping)}</Txt>} chevron={false} />
      </Group>
      <Txt v="footnote">Оплата через Mollie: iDEAL, Bancontact или карта. Вернуть товар можно в течение 14 дней после получения. Продавец: podslushano.nl, KVK 98882317.</Txt>
    </PageScreen>
  );
}

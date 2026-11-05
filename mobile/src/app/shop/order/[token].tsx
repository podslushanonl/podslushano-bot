import { router, useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';
import { euro, useOrder } from '@/api/shop';
import { openUrl } from '@/lib/open';
import { radius, useTheme } from '@/theme';
import { Button, Empty, Group, Icon, IconName, PageScreen, Row, Skeleton, Txt } from '@/ui';

const STEPS: { key: string; title: string }[] = [
  { key: 'paid', title: 'Оплачен' }, { key: 'printing', title: 'В печати' }, { key: 'shipped', title: 'Отправлен' },
];

/** Заказ: статус по шагам, состав, адрес и отслеживание посылки. Сюда же ведёт ссылка из страницы оплаты. */
export default function OrderScreen() {
  const { c } = useTheme();
  const { token } = useLocalSearchParams<{ token: string }>();
  const q = useOrder(String(token));
  const o = q.data;
  if (q.isLoading) return <PageScreen title=""><Skeleton h={200} r={radius.l} /></PageScreen>;
  if (!o) return <PageScreen title=""><Empty icon="box" title="Заказ не найден" /></PageScreen>;
  const reached = STEPS.findIndex((s) => s.key === o.status);
  const head: { icon: IconName; title: string; text: string; tint: string } = o.status === 'new'
    ? { icon: 'clock', title: 'Ждём подтверждения оплаты', text: 'Обычно это занимает несколько секунд.', tint: c.info }
    : o.status === 'failed' || o.status === 'canceled'
      ? { icon: 'warning', title: o.status_ru, text: 'Деньги не списаны. Можно оформить заказ ещё раз.', tint: c.danger }
      : { icon: 'check', title: `Заказ ${o.code}`, text: 'Подтверждение отправили на почту.', tint: c.success };

  return (
    <PageScreen title={`Заказ ${o.code}`} refreshing={q.isRefetching} onRefresh={() => q.refetch()}>
      <View style={{ alignItems: 'center', gap: 10, paddingVertical: 8 }}>
        <View style={{ width: 64, height: 64, borderRadius: 32, backgroundColor: c.bgElevated, borderWidth: 2, borderColor: head.tint, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name={head.icon} size={28} color={head.tint} />
        </View>
        <Txt v="title2" center>{head.title}</Txt>
        <Txt v="callout" tone="muted" center>{head.text}</Txt>
      </View>
      {reached >= 0 ? (
        <View style={{ flexDirection: 'row', gap: 8 }}>
          {STEPS.map((s, i) => (
            <View key={s.key} style={{ flex: 1, gap: 6 }}>
              <View style={{ height: 4, borderRadius: 2, backgroundColor: i <= reached ? c.accent : c.line }} />
              <Txt v="caption" tone={i <= reached ? 'ink' : 'muted'}>{s.title}</Txt>
            </View>
          ))}
        </View>
      ) : null}
      {o.tracking ? <Button kind="secondary" icon="box" title="Отследить посылку" onPress={() => openUrl(o.tracking)} /> : null}
      <Group title="Состав">
        {o.items.map((i, n) => <Row key={n} first={n === 0} title={`${i.title} × ${i.qty}`} sub={i.color || undefined}
          right={<Txt v="bodyStrong">{euro(Number(i.price) * i.qty)}</Txt>} chevron={false} />)}
        <Row title="Доставка" right={<Txt v="bodyStrong">{euro(o.shipping)}</Txt>} chevron={false} />
        <Row title="Итого" right={<Txt v="bodyStrong">{euro(o.total)}</Txt>} chevron={false} />
      </Group>
      <Group title="Доставка">
        <Row first icon="pin" title={o.name} sub={o.address} chevron={false} />
      </Group>
      {o.status === 'failed' || o.status === 'canceled' ? <Button kind="accent" title="В магазин" onPress={() => router.replace('/shop')} /> : null}
      <Txt v="footnote">Вопрос по заказу? Напишите на podslushano.nl@gmail.com и укажите номер {o.code}.</Txt>
    </PageScreen>
  );
}

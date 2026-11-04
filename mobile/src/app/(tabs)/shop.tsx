import { View } from 'react-native';
import { HeaderActions } from '@/features/province/ProvinceSwitch';
import { radius, useTheme } from '@/theme';
import { Card, Group, Icon, Row, TabScreen, Txt } from '@/ui';

/** «Магазин»: мерч podslushano.nl. Шопперы печатаются под заказ. Магазин общий для всех провинций. */
export default function Shop() {
  const { c } = useTheme();
  return (
    <TabScreen title="Магазин" sub="Мерч podslushano.nl" right={<HeaderActions />}>
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
    </TabScreen>
  );
}

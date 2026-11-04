import { View } from 'react-native';
import { HeaderActions, ProvinceSwitch } from '@/features/province/ProvinceSwitch';
import { useProvince } from '@/lib/province';
import { radius, useTheme } from '@/theme';
import { Card, Empty, Icon, IconName, TabScreen, Txt } from '@/ui';

// Типы мест. Данные по провинциям — следующий этап (база мест из открытых источников).
const KINDS: { icon: IconName; title: string }[] = [
  { icon: 'museum', title: 'Музеи' }, { icon: 'castle', title: 'Замки и крепости' }, { icon: 'tree', title: 'Парки и природа' },
  { icon: 'beach', title: 'Пляжи и озёра' }, { icon: 'tag', title: 'Рынки' }, { icon: 'child', title: 'Детям' },
];

/** «Места»: музеи, замки, парки и другие места выбранной провинции. */
export default function Places() {
  const { c } = useTheme();
  const { province } = useProvince();
  const p = province!;
  return (
    <TabScreen title="Места" above={<ProvinceSwitch />} right={<HeaderActions />}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 12 }}>
        {KINDS.map((k) => (
          <View key={k.title} style={{ width: '47.5%', flexGrow: 1, backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: 1, borderColor: c.line,
            padding: 16, gap: 12, opacity: 0.6 }}>
            <View style={{ width: 40, height: 40, borderRadius: radius.s, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
              <Icon name={k.icon} size={22} color={c.accentText} />
            </View>
            <Txt v="headline">{k.title}</Txt>
          </View>
        ))}
      </View>
      <Card style={{ borderRadius: radius.l }}>
        <Empty icon="pin" title={`Собираем места ${p.name}`}
          text="Часы работы, цены, музейная карта и маршрут для каждого места. Раздел откроется в ближайшем обновлении." />
      </Card>
    </TabScreen>
  );
}

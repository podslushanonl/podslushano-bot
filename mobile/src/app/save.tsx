import { View } from 'react-native';
import { MOCK_SAVE } from '@/mocks';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Icon, LargeTitle, PageScreen, Txt } from '@/ui';

/** «Сэкономить»: статьи о скидках, пособиях и выгодных привычках. Список тестовый до этапа 3. */
export default function Save() {
  const { c } = useTheme();
  return (
    <PageScreen title="Сэкономить">
      <LargeTitle title="Сэкономить" sub="Скидки, пособия и привычки, которые берегут деньги в Нидерландах" />
      {MOCK_SAVE.map((a) => (
        <View key={a.id} accessible accessibilityLabel={`${a.tag}: ${a.title}`}
          style={{ flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, backgroundColor: c.bgElevated, borderRadius: radius.card,
            borderWidth: HAIRLINE, borderColor: c.line }}>
          <View style={{ width: 44, height: 44, borderRadius: radius.control, backgroundColor: c.secondarySoft, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="tag" size={20} color={c.secondary} />
          </View>
          <View style={{ flex: 1, gap: 2 }}>
            <Txt v="overline" color={c.secondary}>{a.tag} · {a.mins} мин</Txt>
            <Txt v="headline">{a.title}</Txt>
          </View>
        </View>
      ))}
      <Txt v="footnote" tone="muted">Пример: статьи появятся на этапе 3 вместе с ридером.</Txt>
    </PageScreen>
  );
}

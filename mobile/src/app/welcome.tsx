import { Image } from 'expo-image';
import { router } from 'expo-router';
import { ScrollView, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { fonts, radius, useTheme } from '@/theme';
import { Button, Icon, IconName, Txt } from '@/ui';

const POINTS: { icon: IconName; title: string; text: string }[] = [
  { icon: 'ticket', title: 'Афиша провинции', text: 'Концерты, выставки, фестивали и встречи рядом с вами.' },
  { icon: 'museum', title: 'Места', text: 'Музеи, замки, парки и пляжи с часами работы и ценами.' },
  { icon: 'people', title: 'Контакт-гайд', text: 'Русскоязычные врачи, юристы, мастера и другие специалисты.' },
  { icon: 'guide', title: 'Справочник', text: 'Документы, здоровье, жильё, работа и налоги по шагам.' },
];

/** Первый запуск: что умеет приложение и переход к выбору провинции. */
export default function Welcome() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView contentContainerStyle={{ paddingTop: insets.top + 28, paddingHorizontal: 24, paddingBottom: 150 + insets.bottom, gap: 26 }}>
        <View style={{ gap: 14 }}>
          <Image source={require('../../assets/images/splash-icon.png')} style={{ width: 52, height: 52 }} accessibilityIgnoresInvertColors
            accessible={false} />
          <Txt style={{ fontFamily: fonts.display, fontSize: 26, lineHeight: 30 }} accessibilityRole="header">
            <Txt style={{ fontFamily: fonts.display, fontSize: 26 }} tone="ink">podslushano</Txt>
            <Txt style={{ fontFamily: fonts.display, fontSize: 26 }} color={c.accent}>.nl</Txt>
          </Txt>
          <Txt v="display">Жизнь в Нидерландах на русском</Txt>
          <Txt v="body" tone="muted">Всё нужное о вашей провинции в одном приложении.</Txt>
        </View>
        <View style={{ gap: 16 }}>
          {POINTS.map((p) => (
            <View key={p.title} style={{ flexDirection: 'row', gap: 16, alignItems: 'flex-start' }}>
              <View style={{ width: 44, height: 44, borderRadius: radius.m, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
                <Icon name={p.icon} size={24} color={c.accentText} />
              </View>
              <View style={{ flex: 1, gap: 2 }}>
                <Txt v="headline">{p.title}</Txt>
                <Txt v="subhead" tone="muted">{p.text}</Txt>
              </View>
            </View>
          ))}
        </View>
      </ScrollView>
      <View style={{ position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: 24, paddingTop: 16, paddingBottom: insets.bottom + 20,
        backgroundColor: c.bg, gap: 6 }}>
        <Button kind="accent" title="Выбрать провинцию" onPress={() => router.push({ pathname: '/province', params: { first: '1' } })} />
        <Button kind="plain" title="У меня уже есть аккаунт" onPress={() => router.push('/login')} />
      </View>
    </View>
  );
}

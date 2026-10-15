import { View } from 'react-native';
import { goUrl, SITE } from '@/api/client';
import { openBot, openUrl } from '@/lib/open';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Button, Icon, IconName, PageScreen, Txt } from '@/ui';

function Offer({ icon, over, title, text, children, dark }: { icon: IconName; over: string; title: string; text: string; children: React.ReactNode; dark?: boolean }) {
  const { c } = useTheme();
  return (
    <View style={{ backgroundColor: dark ? c.hero : c.bgElevated, borderRadius: radius.xxl, padding: 20, gap: 10, borderWidth: HAIRLINE, borderColor: c.line }}>
      <View style={{ width: 48, height: 48, borderRadius: 16, backgroundColor: c.accent, alignItems: 'center', justifyContent: 'center' }}>
        <Icon name={icon} size={23} color={c.onAccent} />
      </View>
      <Txt v="overline" color={dark ? c.accent : c.accentText}>{over}</Txt>
      <Txt v="title2" color={dark ? c.onHero : c.ink}>{title}</Txt>
      <Txt v="callout" color={dark ? c.onHeroMuted : c.muted}>{text}</Txt>
      <View style={{ gap: 8, marginTop: 6 }}>{children}</View>
    </View>
  );
}

export default function Save() {
  return (
    <PageScreen title="Сэкономить">
      <View style={{ gap: 6 }}>
        <Txt v="title1">Сэкономить</Txt>
        <Txt v="callout" tone="muted">Проверенные способы платить меньше. Часть ссылок может быть партнёрской — для вас цена та же.</Txt>
      </View>
      <Offer dark icon="shield" over="Медстраховка 2027 · до 31 декабря" title="Не переплачивайте за zorgverzekering"
        text="Базовый пакет у всех страховщиков одинаковый — разница только в цене. 6 вопросов, и вы знаете, что вам нужно.">
        <Button title="6 вопросов в боте" kind="accent" onPress={() => openBot('save_zorg')} />
        <Button title="Сравнить цены" kind="glass" onPress={() => openUrl(goUrl('zorg_compare'))} />
      </Offer>
      <Offer icon="globe" over="Путешествия" title="eSIM: интернет за границей без роуминга"
        text="Покупаете до поездки, включаете по прилёту. Без пластиковой карты и очередей.">
        <Button title="Выбрать eSIM" kind="primary" onPress={() => openBot('save_esim')} />
        <Button title="Подробнее на сайте" kind="secondary" onPress={() => openUrl(`${SITE}/travel/`)} />
      </Offer>
    </PageScreen>
  );
}

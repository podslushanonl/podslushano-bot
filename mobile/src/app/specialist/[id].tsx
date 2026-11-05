import { useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';
import { catTitle, SpecialistLink, useSpecialists } from '@/api/guide';
import { openUrl } from '@/lib/open';
import { radius, useTheme } from '@/theme';
import { Button, Card, Empty, Group, IconName, Img, PageScreen, Row, Skeleton, Txt } from '@/ui';
import { Recommended } from '@/features/guide/SpecialistCard';

const LINK_ICON: Record<string, IconName> = {
  phone: 'phone', whatsapp: 'bubble', telegram: 'paperplane', instagram: 'camera', email: 'mail', site: 'globe', website: 'globe',
};
const LINK_TITLE: Record<string, string> = {
  phone: 'Позвонить', whatsapp: 'WhatsApp', telegram: 'Telegram', instagram: 'Instagram', email: 'Написать на почту', site: 'Сайт', website: 'Сайт',
};

/** Карточка специалиста: описание и все способы связи. */
export default function SpecialistScreen() {
  const { c } = useTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const q = useSpecialists();
  const s = q.data?.find((x) => String(x.id) === id);

  if (q.isLoading) return <PageScreen title=""><Skeleton h={180} r={radius.l} /></PageScreen>;
  if (!s) return <PageScreen title=""><Empty icon="people" title="Карточка не найдена" text="Возможно, специалист убрал её из гайда." /></PageScreen>;

  const where = [s.city, s.province, s.online ? 'онлайн по всей стране' : ''].filter(Boolean).join(' · ');
  const first: SpecialistLink | undefined = s.links[0];
  return (
    <PageScreen title={s.name}
      footer={first ? <Button kind="accent" icon={LINK_ICON[first.type] || 'link'} title={LINK_TITLE[first.type] || first.label || 'Связаться'} onPress={() => openUrl(first.url)} /> : undefined}>
      <View style={{ gap: 8 }}>
        {s.photo ? <Img source={s.photo} style={{ width: 88, height: 88, borderRadius: radius.l, marginBottom: 4 }} accessibilityIgnoresInvertColors /> : null}
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Txt v="overline" tone="accent">{catTitle(s.category)}</Txt>
          {s.premium ? <Recommended /> : null}
        </View>
        <Txt v="title1" accessibilityRole="header">{s.name}</Txt>
        {where ? <Txt v="subhead" tone="muted">{where}</Txt> : null}
      </View>
      {s.description ? <Card pad={18} style={{ borderRadius: radius.l }}><Txt v="body">{s.description}</Txt></Card> : null}
      {s.links.length ? (
        <Group title="Связаться">
          {s.links.map((l, i) => (
            <Row key={l.url} first={i === 0} icon={LINK_ICON[l.type] || 'link'} iconBg={i === 0 ? c.accent : undefined}
              title={LINK_TITLE[l.type] || l.label || l.type} sub={l.url.replace(/^(https?:\/\/|tel:|mailto:)/, '').replace(/\/$/, '')}
              onPress={() => openUrl(l.url)} />
          ))}
        </Group>
      ) : s.contact ? <Card style={{ borderRadius: radius.l }}><Txt v="body" selectable>{s.contact}</Txt></Card> : null}
      <Txt v="footnote">Информацию о себе специалист указал сам. podslushano.nl не отвечает за качество услуг. Если что-то не так, напишите нам.</Txt>
    </PageScreen>
  );
}

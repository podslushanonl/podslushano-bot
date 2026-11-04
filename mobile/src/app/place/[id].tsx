import { useLocalSearchParams } from 'expo-router';
import { View } from 'react-native';
import { hoursLines, kindOf, placeById, PLACES_SOURCE } from '@/api/places';
import { openRoute } from '@/lib/maps';
import { openUrl } from '@/lib/open';
import { provinceById } from '@/lib/provinces';
import { radius, useTheme } from '@/theme';
import { Button, Empty, Group, Img, PageScreen, Row, Txt } from '@/ui';

/** Карточка места: фото, описание, маршрут и сайт. */
export default function PlaceScreen() {
  const { c } = useTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const p = placeById(id);
  if (!p) return <PageScreen title=""><Empty icon="pin" title="Место не найдено" /></PageScreen>;
  const prov = provinceById(p.province);
  return (
    <PageScreen title={p.name} footer={<Button kind="accent" icon="route" title="Построить маршрут" onPress={() => openRoute(p.lat, p.lon, p.name)} />}>
      {p.img ? <Img source={p.img} style={{ width: '100%', aspectRatio: 4 / 3, borderRadius: radius.xl, backgroundColor: c.placeholder }} /> : null}
      <View style={{ gap: 8 }}>
        <Txt v="overline" tone="accent">{p.kinds.map((x) => kindOf(x).one).join(' · ')}</Txt>
        <Txt v="title1" accessibilityRole="header">{p.name}</Txt>
        {p.ru && p.ru !== p.name ? <Txt v="callout" tone="muted">{p.ru}</Txt> : null}
        {p.desc ? <Txt v="body">{p.desc[0].toUpperCase() + p.desc.slice(1)}</Txt> : null}
      </View>
      <Group>
        <Row first icon="pin" title={[p.street, p.town].filter(Boolean).join(', ') || prov?.name || ''} sub={prov?.name} chevron={false} />
        {p.hours ? <Row icon="clock" title="Часы работы" sub={hoursLines(p.hours).join('\n')} chevron={false} /> : null}
        {p.fee ? <Row icon="euro" title="Вход" sub={p.fee.replace(/EUR/g, '€')} chevron={false} /> : null}
        {p.phone ? <Row icon="phone" title="Позвонить" sub={p.phone} onPress={() => openUrl(`tel:${p.phone.replace(/[^+\d]/g, '')}`)} /> : null}
        {p.site ? <Row icon="globe" title="Сайт" sub={p.site.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')} onPress={() => openUrl(p.site)} /> : null}
      </Group>
      <Txt v="footnote">Часы работы и цены могут меняться: перед поездкой проверьте сайт места. Данные: {PLACES_SOURCE}.</Txt>
    </PageScreen>
  );
}

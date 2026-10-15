import { router } from 'expo-router';
import { View } from 'react-native';
import { useDisruptions, useWeather, weatherIcon, weatherText } from '@/api/content';
import { HAIRLINE, radius, useTheme } from '@/theme';
import { Icon, Skeleton, Tap, Txt } from '@/ui';

/** «Сейчас в городе»: погода, дождь в ближайшие часы и сбои поездов — главное за секунду. */
export function NowCard({ city }: { city: string }) {
  const { c } = useTheme();
  const w = useWeather(city);
  const ns = useDisruptions();
  const now = ns.data?.now || [];
  const mine = now.find((d) => `${d.title} ${d.text || ''} ${(d.stations || []).join(' ')}`.includes(city));
  const nsTitle = mine ? mine.title : now.length ? `Сбоев на железной дороге: ${now.length}` : 'Поезда идут по расписанию';
  const nsSub = mine ? (mine.expected || mine.end_ru || mine.type_ru) : now.length ? 'В вашем городе всё спокойно' : 'По данным NS';
  return (
    <View style={{ backgroundColor: c.hero, borderRadius: radius.xxl, borderWidth: HAIRLINE, borderColor: c.line, padding: 18, gap: 16 }}>
      <View style={{ flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <View style={{ gap: 2 }}>
          <Txt v="overline" color={c.accent}>Сейчас в {city}</Txt>
          {w.data ? (
            <>
              <Txt v="display" color={c.onHero} style={{ fontSize: 44, lineHeight: 50 }}>{w.data.temp}°</Txt>
              <Txt v="callout" color={c.onHeroMuted}>
                {weatherText(w.data.code)}{w.data.rainSoon ? `, дождь около ${w.data.rainSoon}` : ''}
              </Txt>
            </>
          ) : <View style={{ gap: 8, paddingTop: 8 }}><Skeleton w={90} h={40} /><Skeleton w={160} h={14} /></View>}
        </View>
        {w.data ? <Icon name={weatherIcon(w.data.code)} size={54} color={c.accent} /> : null}
      </View>
      <Tap onPress={() => router.push('/trains')} scaleTo={0.98}
        style={{ flexDirection: 'row', alignItems: 'center', gap: 12, borderRadius: radius.l, padding: 12,
          backgroundColor: c.heroInner }}>
        <View style={{ width: 38, height: 38, borderRadius: 12, backgroundColor: mine ? c.accent : c.heroInner2, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="train" size={19} color={mine ? c.onAccent : c.onHero} />
        </View>
        <View style={{ flex: 1, gap: 1 }}>
          <Txt v="bodyStrong" color={c.onHero} numberOfLines={2}>{nsTitle}</Txt>
          <Txt v="footnote" color={c.onHeroMuted} numberOfLines={1}>{nsSub}</Txt>
        </View>
        <Icon name="chevron" size={14} color={c.onHeroMuted} />
      </Tap>
    </View>
  );
}

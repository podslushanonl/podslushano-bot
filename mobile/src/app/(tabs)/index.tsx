import { router } from 'expo-router';
import { View } from 'react-native';
import { useDisruptions, useWeather, weatherIcon, weatherText } from '@/api/content';
import { EventCard } from '@/features/feed/cards';
import { useProvinceEvents } from '@/features/province/data';
import { HeaderActions, ProvinceSwitch } from '@/features/province/ProvinceSwitch';
import { plural } from '@/lib/format';
import { useProvince } from '@/lib/province';
import { radius, useTheme } from '@/theme';
import { Button, Card, Empty, Group, Icon, Row, Skeleton, TabScreen, Tap, Txt } from '@/ui';

const dateLine = () => new Date().toLocaleDateString('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'Europe/Amsterdam' });

/** Блок с заголовком и ссылкой «Все» справа. */
function Section({ title, more, onMore, children }: { title: string; more?: string; onMore?: () => void; children: React.ReactNode }) {
  return (
    <View style={{ gap: 12 }}>
      <View style={{ flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <Txt v="title2" accessibilityRole="header">{title}</Txt>
        {more && onMore ? <Tap onPress={onMore} hitSlop={10}><Txt v="subhead" tone="accent">{more}</Txt></Tap> : null}
      </View>
      {children}
    </View>
  );
}

/** «Сегодня»: погода, ближайшие события, поезда и коротко о провинции. */
export default function Today() {
  const { c } = useTheme();
  const { province } = useProvince();
  const p = province!;
  const w = useWeather(p.capital, [p.lat, p.lon]);
  const ev = useProvinceEvents(p.id);
  const dis = useDisruptions();
  const now = dis.data?.now?.length || 0;

  return (
    <TabScreen title="Сегодня" sub={dateLine()} above={<ProvinceSwitch />} right={<HeaderActions />}
      refreshing={ev.isRefetching} onRefresh={() => Promise.all([ev.refetch(), w.refetch(), dis.refetch()])}>
      {/* Погода в провинции */}
      <Card pad={18} style={{ borderRadius: radius.l, flexDirection: 'row', alignItems: 'center', gap: 16 }}>
        {w.data ? (
          <>
            <View style={{ width: 56, height: 56, borderRadius: radius.m, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
              <Icon name={weatherIcon(w.data.code)} size={28} color={c.accentText} />
            </View>
            <View style={{ flex: 1, gap: 2 }}>
              <Txt v="title1">{w.data.temp}°</Txt>
              <Txt v="subhead" tone="muted">
                {weatherText(w.data.code)}, ветер {w.data.wind} км/ч{w.data.rainSoon ? `, дождь около ${w.data.rainSoon}` : ''}
              </Txt>
            </View>
          </>
        ) : <Skeleton h={56} />}
      </Card>

      <Section title="Ближайшие события" more="Вся афиша" onMore={() => router.push('/afisha')}>
        {ev.isLoading ? <View style={{ gap: 12 }}>{[0, 1].map((i) => <Skeleton key={i} h={122} r={radius.xl} />)}</View>
          : ev.events.length ? ev.events.slice(0, 3).map((e) => <EventCard key={e.key} e={e} />)
            : <Card style={{ borderRadius: radius.l }}><Empty icon="ticket" title={`В ${p.name} пока нет событий`} text="Афиша пополняется каждую неделю." /></Card>}
      </Section>

      <Group title="В дороге">
        <Row first icon="train" iconBg={now ? c.danger : c.success} title="Поезда NS"
          sub={now ? `${now} ${plural(now, ['сбой', 'сбоя', 'сбоев'])} сейчас` : 'Сбоев сейчас нет'} onPress={() => router.push('/trains')} />
      </Group>

      <Section title={p.name}>
        <Card pad={18} style={{ borderRadius: radius.l, gap: 10 }}>
          <Txt v="body">{p.short}</Txt>
          <Txt v="subhead" tone="muted">Столица провинции: {p.capital}</Txt>
          <Button kind="secondary" size="s" full={false} icon="pin" title="Места провинции" onPress={() => router.push('/places')} />
        </Card>
      </Section>
    </TabScreen>
  );
}

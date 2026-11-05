import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Modal, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useDepartures, useDisruptions, useStations } from '@/api/content';
import { openBot } from '@/lib/open';
import { useProvince } from '@/lib/province';
import { setMyStation, useMyStation } from '@/lib/station';
import { HAIRLINE, radius, type as T, useTheme } from '@/theme';
import { Button, Icon, IconButton, LargeTitle, Segmented, PageScreen, Skeleton, Tap, Txt } from '@/ui';

export default function Trains() {
  const { c } = useTheme();
  const { home } = useProvince();
  const my = useMyStation();
  const st = my.st;
  const [picker, setPicker] = useState(false);
  const [kind, setKind] = useState<'departures' | 'arrivals'>('departures');
  const deps = useDepartures(st[0], kind);
  const dep = useDepartures(st[0], 'departures');
  // Какие поезда здесь останавливаются — по ближайшим отправлениям (на части станций только Sprinter)
  const kinds = useMemo(() => [...new Set((dep.data || []).filter((d) => !d.cancelled).map((d) => (d.code && KIND[d.code]) || d.category).filter(Boolean))], [dep.data]);
  const dis = useDisruptions();
  const mine = useMemo(() => [...(dis.data?.now || []), ...(dis.data?.planned || [])].filter((d) => (d.stations || []).includes(st[0])), [dis.data, st]);
  const choose = (s: [string, string]) => { setMyStation(s, home?.name || ''); setPicker(false); };

  return (
    <PageScreen title="Поезда NS" refreshing={deps.isRefetching} onRefresh={() => { deps.refetch(); dis.refetch(); }}>
      <LargeTitle title="Поезда NS" sub="Отправления и сбои на вашей станции" />
      <Tap onPress={() => setPicker(true)} scaleTo={0.98} accessibilityLabel={`Станция ${st[1]}. Сменить`}
        style={{ backgroundColor: c.bgElevated, borderRadius: radius.l, borderWidth: HAIRLINE, borderColor: c.line, padding: 18,
          flexDirection: 'row', alignItems: 'center', gap: 16 }}>
        <View style={{ width: 56, height: 56, borderRadius: radius.m, backgroundColor: c.accentSoft, alignItems: 'center', justifyContent: 'center' }}>
          <Icon name="train" size={28} color={c.accentText} />
        </View>
        <View style={{ flex: 1, gap: 2 }}>
          <Txt v="footnote" tone="muted">{my.source === 'own' ? 'Ваша станция' : my.source === 'home' ? `Рядом с домом · ${Math.max(1, Math.round(my.km!))}\u00a0км` : 'Вокзал провинции'}</Txt>
          <Txt v="title2" numberOfLines={1}>{st[1]}</Txt>
        </View>
        <Txt v="subhead" color={c.accentText} style={{ fontFamily: 'Onest_600SemiBold' }}>Сменить</Txt>
      </Tap>
      {my.source === 'main' ? (
        <Tap onPress={() => router.push('/province')} accessibilityRole="button" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: -6 }}>
          <Icon name="home" size={16} color={c.accentText} />
          <Txt v="subhead" tone="accent" style={{ flex: 1 }}>Укажите, где живёте, — покажем ближайшую к дому станцию</Txt>
        </Tap>
      ) : null}

      {dis.isLoading ? <Skeleton h={70} r={22} /> : mine.length ? mine.map((d) => (
        <View key={d.id} style={{ backgroundColor: d.type === 'MAINTENANCE' ? c.bgElevated : c.accentSoft, borderRadius: radius.xl, padding: 16, gap: 6,
          borderWidth: 1, borderColor: d.type === 'MAINTENANCE' ? c.line : 'transparent' }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <Icon name={d.type === 'MAINTENANCE' ? 'calendar' : 'warning'} size={16} color={d.type === 'MAINTENANCE' ? c.info : c.accentText} />
            <Txt v="overline" color={d.type === 'MAINTENANCE' ? c.info : c.accentText}>{d.type_ru}{!d.active && d.start_ru ? ` · с ${d.start_ru}` : ''}</Txt>
          </View>
          <Txt v="headline">{d.title}</Txt>
          {d.situation ? <Txt v="callout" tone="ink">{d.situation}</Txt> : null}
          {d.text ? <Txt v="callout" tone="muted">{d.text}</Txt> : null}
          {d.expected ? <Txt v="footnote">{d.expected}</Txt> : null}
        </View>
      )) : (
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12, backgroundColor: c.bgElevated, borderRadius: radius.xl, padding: 16, borderWidth: 1, borderColor: c.line }}>
          <View style={{ width: 34, height: 34, borderRadius: 17, backgroundColor: c.success, alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="check" size={17} color="#FFFFFF" />
          </View>
          <Txt v="bodyStrong" style={{ flex: 1 }}>{dis.isError ? 'Не удалось проверить сбои' : 'На этой станции сбоев нет'}</Txt>
        </View>
      )}

      <View style={{ gap: 10 }}>
        <Segmented items={[{ key: 'departures', title: 'Отправление' }, { key: 'arrivals', title: 'Прибытие' }]} value={kind} onChange={setKind} />
        {kinds.length ? <Txt v="footnote">Останавливаются: {kinds.join(', ')}</Txt> : null}
        <View style={{ backgroundColor: c.bgElevated, borderRadius: radius.xl, borderWidth: 1, borderColor: c.line, overflow: 'hidden' }}>
          {deps.isLoading ? <View style={{ padding: 16, gap: 14 }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={34} />)}</View>
            : !deps.data?.length ? <Txt v="callout" tone="muted" style={{ padding: 16 }}>
              {deps.isError ? 'Не удалось загрузить расписание. Потяните вниз, чтобы обновить.' : (kind === 'arrivals' ? 'Ближайших прибытий нет.' : 'Ближайших отправлений нет.') + ' Ночью поезда почти не ходят.'}</Txt>
            : deps.data.map((d, i) => (
              <View key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 12, borderTopWidth: i ? 1 : 0, borderTopColor: c.line }}>
                <View style={{ width: 54 }}>
                  <Txt v="headline" style={[{ fontVariant: ['tabular-nums'] }, d.cancelled && { textDecorationLine: 'line-through', color: c.muted }]}>{d.time}</Txt>
                  {d.delay && !d.cancelled ? <Txt v="caption" tone="danger" style={{ fontFamily: 'Onest_700Bold' }}>+{d.delay}</Txt> : null}
                </View>
                <View style={{ flex: 1, gap: 2 }}>
                  <Txt v="bodyStrong" numberOfLines={1} style={d.cancelled ? { textDecorationLine: 'line-through', color: c.muted } : undefined}>
                    {kind === 'arrivals' ? `из ${d.direction}` : d.direction}</Txt>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                    {d.code ? <TrainKind code={d.code} /> : null}
                    <Txt v="footnote" numberOfLines={1} style={{ flexShrink: 1 }}>
                      {d.cancelled ? 'Отменён' : [d.code ? '' : d.category, kind === 'departures' && d.via?.length ? `через ${d.via.slice(0, 2).join(', ')}` : ''].filter(Boolean).join(' · ')}</Txt>
                  </View>
                </View>
                <View style={{ minWidth: 36, height: 36, paddingHorizontal: 6, borderRadius: 10, backgroundColor: d.track_changed ? c.accent : c.bgSunken, alignItems: 'center', justifyContent: 'center' }}>
                  <Txt v="headline" color={d.track_changed ? c.onAccent : c.ink}>{d.track || '—'}</Txt>
                </View>
              </View>
            ))}
        </View>
        <Txt v="footnote">Данные NS, обновляются каждую минуту. Оранжевый номер пути — путь изменился.</Txt>
      </View>

      <Button title="Уведомления о сбоях в Telegram" kind="secondary" icon="bell" onPress={() => openBot(`ns_${st[0]}`)} />
      <StationPicker visible={picker} onClose={() => setPicker(false)} onPick={choose} />
    </PageScreen>
  );
}

function StationPicker({ visible, onClose, onPick }: { visible: boolean; onClose: () => void; onPick: (s: [string, string]) => void }) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const list = useStations();
  const [q, setQ] = useState('');
  const found = useMemo(() => {
    const t = q.trim().toLowerCase();
    const all = list.data?.list || [];
    return t ? all.filter(([, n]) => n.toLowerCase().includes(t)) : all;
  }, [q, list.data]);
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: 16 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, gap: 10 }}>
          <Txt v="title2" style={{ flex: 1 }}>Станция</Txt>
          <IconButton icon="close" label="Закрыть" onPress={onClose} size={38} />
        </View>
        <View style={{ padding: 16 }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, height: 50, borderRadius: radius.l,
            backgroundColor: c.bgElevated, borderWidth: HAIRLINE, borderColor: c.line }}>
            <Icon name="search" size={18} color={c.muted} />
            <TextInput value={q} onChangeText={setQ} placeholder="Например, Amsterdam" placeholderTextColor={c.faint} autoFocus
              style={[T.callout, { flex: 1, color: c.ink, outlineStyle: 'none' } as any]} />
          </View>
        </View>
        <FlatList data={found} keyExtractor={(x) => x[0]} keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: insets.bottom + 20 }}
          renderItem={({ item }) => (
            <Tap onPress={() => { onPick(item); setQ(''); }} scaleTo={0.99} style={{ paddingHorizontal: 20, paddingVertical: 15, borderBottomWidth: 1, borderBottomColor: c.line }}>
              <Txt v="bodyStrong">{item[1]}</Txt>
            </Tap>
          )} />
      </View>
    </Modal>
  );
}


/** Значок типа поезда: Intercity — тёмный, Sprinter — светлый, остальные — нейтральные. */
const KIND: Record<string, string> = { IC: 'Intercity', ICD: 'Intercity Direct', SPR: 'Sprinter', ST: 'Stoptrein', SNEL: 'Sneltrein', ICE: 'ICE', EST: 'Eurostar', NSI: 'International' };
function TrainKind({ code }: { code: string }) {
  const { c } = useTheme();
  const ic = code === 'IC' || code === 'ICD';
  return (
    <View style={{ paddingHorizontal: 6, height: 18, borderRadius: 5, justifyContent: 'center',
      backgroundColor: ic ? c.ink : code === 'SPR' ? c.accentSoft : c.bgSunken }}>
      <Txt v="caption" color={ic ? c.bg : code === 'SPR' ? c.accentText : c.ink} style={{ fontFamily: 'Onest_700Bold' }}>{KIND[code] || code}</Txt>
    </View>
  );
}

import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useMemo, useState } from 'react';
import { FlatList, Modal, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useDepartures, useDisruptions, useStations } from '@/api/content';
import { openBot } from '@/lib/open';
import { HAIRLINE, radius, type as T, useTheme } from '@/theme';
import { Button, Glass, Icon, IconButton, PageScreen, Skeleton, Tap, Txt } from '@/ui';

const KEY = 'ns_station';
const DEFAULT: [string, string] = ['UT', 'Utrecht Centraal'];

export default function Trains() {
  const { c } = useTheme();
  const [st, setSt] = useState<[string, string]>(DEFAULT);
  const [picker, setPicker] = useState(false);
  useEffect(() => { AsyncStorage.getItem(KEY).then((v) => { if (v) setSt(JSON.parse(v)); }).catch(() => {}); }, []);
  const deps = useDepartures(st[0]);
  const dis = useDisruptions();
  const mine = useMemo(() => [...(dis.data?.now || []), ...(dis.data?.planned || [])].filter((d) => (d.stations || []).includes(st[0])), [dis.data, st]);
  const choose = (s: [string, string]) => { setSt(s); setPicker(false); AsyncStorage.setItem(KEY, JSON.stringify(s)).catch(() => {}); };

  return (
    <PageScreen title="Поезда NS" refreshing={deps.isRefetching} onRefresh={() => { deps.refetch(); dis.refetch(); }}>
      <Tap onPress={() => setPicker(true)} scaleTo={0.98} accessibilityLabel={`Станция ${st[1]}. Сменить`}
        style={{ backgroundColor: c.hero, borderRadius: radius.xxl, borderWidth: HAIRLINE, borderColor: c.line, padding: 20, gap: 4 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <Icon name="train" size={16} color={c.accent} />
          <Txt v="overline" color={c.accent}>Ваша станция</Txt>
        </View>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <Txt v="title1" color={c.onHero} style={{ flex: 1 }}>{st[1]}</Txt>
          <Txt v="subhead" color={c.onHeroMuted} style={{ fontFamily: 'Onest_600SemiBold' }}>Сменить</Txt>
        </View>
      </Tap>

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
        <Txt v="title2">Отправления</Txt>
        <View style={{ backgroundColor: c.bgElevated, borderRadius: radius.xl, borderWidth: 1, borderColor: c.line, overflow: 'hidden' }}>
          {deps.isLoading ? <View style={{ padding: 16, gap: 14 }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={34} />)}</View>
            : !deps.data?.length ? <Txt v="callout" tone="muted" style={{ padding: 16 }}>Нет данных о поездах.</Txt>
            : deps.data.map((d, i) => (
              <View key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 12, borderTopWidth: i ? 1 : 0, borderTopColor: c.line }}>
                <View style={{ width: 54 }}>
                  <Txt v="headline" style={[{ fontVariant: ['tabular-nums'] }, d.cancelled && { textDecorationLine: 'line-through', color: c.muted }]}>{d.time}</Txt>
                  {d.delay && !d.cancelled ? <Txt v="caption" tone="danger" style={{ fontFamily: 'Onest_700Bold' }}>+{d.delay}</Txt> : null}
                </View>
                <View style={{ flex: 1 }}>
                  <Txt v="bodyStrong" numberOfLines={1} style={d.cancelled ? { textDecorationLine: 'line-through', color: c.muted } : undefined}>{d.direction}</Txt>
                  <Txt v="footnote" numberOfLines={1}>{d.cancelled ? 'Отменён' : [d.category, d.via?.length ? `через ${d.via.slice(0, 2).join(', ')}` : ''].filter(Boolean).join(' · ')}</Txt>
                </View>
                <View style={{ minWidth: 36, height: 36, paddingHorizontal: 6, borderRadius: 10, backgroundColor: d.track_changed ? c.accent : c.bgSunken, alignItems: 'center', justifyContent: 'center' }}>
                  <Txt v="headline" color={d.track_changed ? c.onAccent : c.ink}>{d.track || '—'}</Txt>
                </View>
              </View>
            ))}
        </View>
        <Txt v="footnote">Данные NS, обновляются каждую минуту. Оранжевый номер — поезд уйдёт с другого пути.</Txt>
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
    const all = list.data || [];
    return (t ? all.filter(([, n]) => n.toLowerCase().includes(t)) : all).slice(0, 80);
  }, [q, list.data]);
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: c.bg, paddingTop: 16 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, gap: 10 }}>
          <Txt v="title2" style={{ flex: 1 }}>Станция</Txt>
          <IconButton icon="close" label="Закрыть" onPress={onClose} kind="solid" size={38} />
        </View>
        <View style={{ padding: 16 }}>
          <Glass radius={radius.l} strong style={{ flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 14, height: 50 }}>
            <Icon name="search" size={18} color={c.muted} />
            <TextInput value={q} onChangeText={setQ} placeholder="Например, Amsterdam" placeholderTextColor={c.faint} autoFocus
              style={[T.callout, { flex: 1, color: c.ink, outlineStyle: 'none' } as any]} />
          </Glass>
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

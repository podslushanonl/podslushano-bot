import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { FlatList, Linking, Modal, Pressable, RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { Button, Card, Eyebrow, H, P } from '@/components/ui';
import { C } from '@/constants/theme';
import { Departure, Disruption, TG_BOT, departures, disruptions, stations } from '@/lib/api';

const KEY = 'ns_station';
const DEFAULT: [string, string] = ['UT', 'Utrecht Centraal'];

export default function Trains() {
  const [st, setSt] = useState<[string, string]>(DEFAULT);
  const [list, setList] = useState<[string, string][]>([]);
  const [deps, setDeps] = useState<Departure[] | null>(null);
  const [dis, setDis] = useState<Disruption[]>([]);
  const [disState, setDisState] = useState<'loading' | 'ok' | 'error'>('loading');
  const [picker, setPicker] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(KEY).then((v) => { if (v) setSt(JSON.parse(v)); }).catch(() => {});
    stations().then(setList).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    const [d, x] = await Promise.allSettled([departures(st[0]), disruptions()]);
    setDeps(d.status === 'fulfilled' ? d.value : []);
    if (x.status === 'fulfilled') {
      const all = [...(x.value.now || []), ...(x.value.planned || [])];
      setDis(all.filter((i) => (i.stations || []).includes(st[0])));
      setDisState('ok');
    } else {
      setDisState('error');
    }
  }, [st]);

  useEffect(() => {
    const first = setTimeout(load, 0);
    const t = setInterval(load, 60000);
    return () => { clearTimeout(first); clearInterval(t); };
  }, [load]);

  const choose = (s: [string, string]) => {
    setSt(s); setPicker(false); setDeps(null); setDisState('loading');
    AsyncStorage.setItem(KEY, JSON.stringify(s)).catch(() => {});
  };

  const refresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  return (
    <ScrollView contentContainerStyle={{ padding: 16, gap: 14 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={C.accent} />}>
      <Pressable onPress={() => setPicker(true)} style={s.pick}>
        <View style={{ flex: 1 }}>
          <Eyebrow color={C.muted}>Ваша станция</Eyebrow>
          <H size={22}>{st[1]}</H>
        </View>
        <Text style={s.change}>Сменить</Text>
      </Pressable>

      {dis.length ? dis.map((d) => (
        <Card key={d.id} style={{ borderLeftWidth: 5, borderLeftColor: d.type === 'MAINTENANCE' ? C.info : C.accent }}>
          <Eyebrow color={d.type === 'MAINTENANCE' ? C.info : C.accent}>{d.type_ru}{d.active ? '' : d.start_ru ? ` · с ${d.start_ru}` : ''}</Eyebrow>
          <H size={16}>{d.title}</H>
          {d.situation ? <P>{d.situation}</P> : null}
          {d.text ? <P muted>{d.text}</P> : null}
        </Card>
      )) : disState === 'ok' ? (
        <Card style={{ flexDirection: 'row', alignItems: 'center', gap: 10 }}>
          <View style={s.okDot} /><P>На этой станции сбоев нет.</P>
        </Card>
      ) : (
        <Card><P muted>{disState === 'error' ? 'Не удалось проверить сбои. Потяните вниз, чтобы обновить.' : 'Проверяем сбои…'}</P></Card>
      )}

      <Card>
        <Eyebrow color={C.muted}>Отправления</Eyebrow>
        {deps === null ? <P muted>Загружаем табло…</P> : deps.length === 0 ? <P muted>Нет данных о поездах.</P> :
          deps.map((d, i) => (
            <View key={i} style={[s.dep, i > 0 && { borderTopWidth: 1, borderTopColor: C.line }]}>
              <Text style={[s.time, d.cancelled && s.strike]}>{d.time}</Text>
              <View style={{ flex: 1 }}>
                <Text style={[s.dir, d.cancelled && s.strike]} numberOfLines={1}>{d.direction}</Text>
                <Text style={s.meta}>{d.category}{d.cancelled ? ' · отменён' : d.delay ? ` · +${d.delay} мин` : ''}</Text>
              </View>
              <Text style={[s.track, d.track_changed && { color: C.accent }]}>{d.track || '—'}</Text>
            </View>
          ))}
      </Card>

      <Button title="Уведомления о сбоях в Telegram" soft onPress={() => Linking.openURL(`${TG_BOT}?start=ns_${st[0]}`)} />
      <P muted>Данные NS, обновляются каждую минуту.</P>

      <StationPicker visible={picker} list={list} onClose={() => setPicker(false)} onPick={choose} />
    </ScrollView>
  );
}

function StationPicker({ visible, list, onClose, onPick }: { visible: boolean; list: [string, string][]; onClose: () => void; onPick: (s: [string, string]) => void }) {
  const [q, setQ] = useState('');
  const found = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (t ? list.filter(([, n]) => n.toLowerCase().includes(t)) : list).slice(0, 60);
  }, [q, list]);
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: C.bg, padding: 16, gap: 12 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <H size={22}>Выберите станцию</H>
          <View style={{ flex: 1 }} />
          <Pressable onPress={onClose}><Text style={s.change}>Закрыть</Text></Pressable>
        </View>
        <TextInput value={q} onChangeText={setQ} placeholder="Например, Amsterdam" placeholderTextColor={C.muted} style={s.input} autoFocus />
        <FlatList data={found} keyExtractor={(x) => x[0]} keyboardShouldPersistTaps="handled"
          renderItem={({ item }) => (
            <Pressable onPress={() => { onPick(item); setQ(''); }} style={s.stRow}><Text style={s.dir}>{item[1]}</Text></Pressable>
          )} />
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  pick: { flexDirection: 'row', alignItems: 'center', backgroundColor: C.card, borderRadius: 24, padding: 16, borderWidth: 1, borderColor: C.line },
  change: { color: C.accent, fontWeight: '700', fontSize: 15 },
  okDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: C.ok },
  dep: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 10 },
  time: { fontSize: 17, fontWeight: '800', color: C.ink, width: 52, fontVariant: ['tabular-nums'] },
  dir: { fontSize: 15, fontWeight: '600', color: C.ink },
  meta: { fontSize: 13, color: C.muted, marginTop: 2 },
  track: { fontSize: 17, fontWeight: '800', color: C.ink, minWidth: 28, textAlign: 'right' },
  strike: { textDecorationLine: 'line-through', color: C.muted },
  input: { backgroundColor: C.card, borderRadius: 16, borderWidth: 1, borderColor: C.line, paddingHorizontal: 16, paddingVertical: 12, fontSize: 16, color: C.ink },
  stRow: { paddingVertical: 14, borderBottomWidth: 1, borderBottomColor: C.line },
});

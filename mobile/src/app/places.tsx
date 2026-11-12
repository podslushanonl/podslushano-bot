import { useMemo, useState } from 'react';
import { View } from 'react-native';
import { KINDS, PlaceKind, placesOf, PLACES_SOURCE } from '@/api/places';
import { PlaceCard } from '@/features/places/PlaceCard';
import { HeaderActions, ProvinceSwitch } from '@/features/province/ProvinceSwitch';
import { useProvince } from '@/lib/province';
import { Button, ChipRow, Empty, TabScreen, Txt } from '@/ui';

const PAGE = 30;

/** «Места»: музеи, замки, природа, пляжи, мельницы и места для детей выбранной провинции. */
export default function Places() {
  const { province } = useProvince();
  const p = province!;
  const all = useMemo(() => placesOf(p.id), [p.id]);
  const [kind, setKind] = useState<PlaceKind | ''>('');
  const [town, setTown] = useState('');
  const [limit, setLimit] = useState(PAGE);

  const kinds = KINDS.map((k) => ({ ...k, n: all.filter((x) => x.kinds.includes(k.key)).length })).filter((k) => k.n);
  const byKind = all.filter((x) => !kind || x.kinds.includes(kind));
  // Города — только те, где есть хотя бы 3 места выбранного типа: длинный хвост деревень не нужен в фильтре
  const towns = useMemo(() => {
    const n = new Map<string, number>();
    byKind.forEach((x) => x.town && n.set(x.town, (n.get(x.town) || 0) + 1));
    return [...n.entries()].filter(([, v]) => v >= 3).sort((a, b) => b[1] - a[1]).map(([t]) => t).slice(0, 12);
  }, [byKind]);
  const shown = byKind.filter((x) => !town || x.town === town);

  const pickKind = (k: PlaceKind | '') => { setKind(k); setTown(''); setLimit(PAGE); };

  return (
    <TabScreen title="Места" above={<ProvinceSwitch />} right={<HeaderActions />}>
      <View style={{ gap: 10, marginHorizontal: -16 }}>
        <ChipRow items={[{ key: '' as const, title: `Все ${all.length}` }, ...kinds.map((k) => ({ key: k.key, title: `${k.title} ${k.n}` }))]}
          value={kind} onChange={pickKind} />
        {towns.length > 1 ? <ChipRow items={[{ key: '', title: 'Все города' }, ...towns.map((t) => ({ key: t, title: t }))]} value={town}
          onChange={(t) => { setTown(t); setLimit(PAGE); }} /> : null}
      </View>
      {shown.length ? (
        <View style={{ gap: 10 }}>
          {shown.slice(0, limit).map((x) => <PlaceCard key={x.id} p={x} />)}
          {shown.length > limit ? <Button kind="secondary" title={`Показать ещё ${Math.min(PAGE, shown.length - limit)}`} onPress={() => setLimit(limit + PAGE)} /> : null}
          <Txt v="caption" center>{PLACES_SOURCE}</Txt>
        </View>
      ) : <Empty icon="pin" title="Здесь пока пусто" text="Попробуйте другой тип места или город." />}
    </TabScreen>
  );
}

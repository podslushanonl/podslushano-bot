import { View } from 'react-native';

// Флаги стран входа, нарисованные полосами (без эмодзи и картинок): чёткие на любом экране.
const FLAGS = {
  NL: { dir: 'column', bands: ['#AE1C28', '#FFFFFF', '#21468B'] },
  DE: { dir: 'column', bands: ['#000000', '#DD0000', '#FFCE00'] },
  BE: { dir: 'row', bands: ['#000000', '#FDDA24', '#EF3340'] },
  UA: { dir: 'column', bands: ['#0057B7', '#FFD700'] },
} as const;

export type FlagCode = keyof typeof FLAGS;

export function Flag({ code, size = 22 }: { code: FlagCode; size?: number }) {
  const f = FLAGS[code];
  return (
    <View style={{ width: size, height: Math.round(size * 0.72), borderRadius: 4, overflow: 'hidden', flexDirection: f.dir,
      borderWidth: 0.5, borderColor: 'rgba(0,0,0,0.12)' }}>
      {f.bands.map((b) => <View key={b} style={{ flex: 1, backgroundColor: b }} />)}
    </View>
  );
}

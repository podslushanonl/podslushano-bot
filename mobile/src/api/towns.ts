import { useQuery } from '@tanstack/react-query';
import { Home } from '@/lib/province';
import { PROVINCES, ProvinceId } from '@/lib/provinces';

// Населённые пункты Нидерландов — государственный справочник адресов PDOK (Kadaster), открытый и без ключа.
// Ищем только woonplaats: город или деревня, без улиц и адресов.
const PDOK = 'https://api.pdok.nl/bzk/locatieserver/search/v3_1';
const FL = 'woonplaatsnaam,gemeentenaam,provincienaam,centroide_ll';

export type Town = Home & { province: ProvinceId };

const norm = (s: string) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z]/g, '');
// PDOK пишет Friesland по-фризски
const PROV: Record<string, ProvinceId> = { fryslan: 'fr' };
for (const p of PROVINCES) PROV[norm(p.name)] = p.id;

type Doc = { woonplaatsnaam?: string; gemeentenaam?: string; provincienaam?: string; centroide_ll?: string };

function toTown(d: Doc): Town | null {
  const m = /POINT\(([-\d.]+) ([-\d.]+)\)/.exec(d.centroide_ll || '');
  const province = PROV[norm(d.provincienaam || '')];
  if (!m || !province || !d.woonplaatsnaam) return null;
  return { name: d.woonplaatsnaam, gemeente: d.gemeentenaam || '', lat: Number(m[2]), lon: Number(m[1]), province };
}

async function get(url: string): Promise<Town[]> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const d = await r.json();
  return ((d?.response?.docs || []) as Doc[]).map(toTown).filter(Boolean) as Town[];
}

/** Поиск города или деревни по названию: «Oss», «Berghem», «Den Bosch». */
export const useTownSearch = (q: string) => {
  const t = q.trim();
  return useQuery({
    queryKey: ['towns', t.toLowerCase()], enabled: t.length >= 2, staleTime: 24 * 3600_000,
    queryFn: () => get(`${PDOK}/free?q=${encodeURIComponent(t)}&fq=type:woonplaats&rows=12&fl=${FL}`),
  });
};

/** Город или деревня по координатам (геолокация телефона). */
export async function townAt(lat: number, lon: number): Promise<Town | null> {
  const list = await get(`${PDOK}/reverse?lat=${lat}&lon=${lon}&type=woonplaats&rows=1&fl=${FL}`);
  return list[0] || null;
}

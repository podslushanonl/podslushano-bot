import type { IconName } from '@/ui';
import type { ProvinceId } from '@/lib/provinces';

// База мест: собирается скриптом tools/build_places.py из OpenStreetMap (ODbL) и Wikidata (CC0), фото — Wikimedia Commons.
// Лежит в приложении, поэтому раздел работает и без интернета (кроме фото).
export type PlaceKind = 'museum' | 'castle' | 'nature' | 'beach' | 'windmill' | 'kids';
export type Place = {
  id: string; name: string; ru: string; desc: string; kinds: PlaceKind[]; province: ProvinceId;
  town: string; street: string; lat: number; lon: number; site: string; phone: string;
  /** Часы работы в формате OpenStreetMap: «Tu-Su 10:00-17:00; Mo off». */
  hours: string; fee: string; img: string; rank: number;
};

const DB: { source: string; built: string; places: Place[] } = require('@/data/places.json');

export const PLACES_SOURCE = DB.source;

export const KINDS: { key: PlaceKind; title: string; one: string; icon: IconName }[] = [
  { key: 'museum', title: 'Музеи', one: 'Музей', icon: 'museum' },
  { key: 'castle', title: 'Замки и крепости', one: 'Замок', icon: 'castle' },
  { key: 'nature', title: 'Парки и природа', one: 'Парк', icon: 'tree' },
  { key: 'beach', title: 'Пляжи', one: 'Пляж', icon: 'beach' },
  { key: 'windmill', title: 'Мельницы', one: 'Мельница', icon: 'windmill' },
  { key: 'kids', title: 'Детям', one: 'Детям', icon: 'child' },
];
export const kindOf = (k: PlaceKind) => KINDS.find((x) => x.key === k)!;

/** Места провинции, самые известные сверху. */
export const placesOf = (pid: ProvinceId) => DB.places.filter((p) => p.province === pid);
export const placeById = (id: string) => DB.places.find((p) => p.id === id);

const DAYS: Record<string, string> = { Mo: 'Пн', Tu: 'Вт', We: 'Ср', Th: 'Чт', Fr: 'Пт', Sa: 'Сб', Su: 'Вс', PH: 'праздники' };
const MONTHS: Record<string, string> = { Jan: 'янв', Feb: 'фев', Mar: 'мар', Apr: 'апр', May: 'мая', Jun: 'июн', Jul: 'июл', Aug: 'авг', Sep: 'сен', Oct: 'окт', Nov: 'ноя', Dec: 'дек' };

/** Часы работы OpenStreetMap по-русски, по строке на правило. Сложные правила показываем как есть. */
export function hoursLines(h: string): string[] {
  if (!h) return [];
  if (h.trim() === '24/7') return ['Круглосуточно'];
  return h.split(';').map((r) => r.trim()).filter(Boolean).map((r) => r
    .replace(/\b(Mo|Tu|We|Th|Fr|Sa|Su|PH)\b/g, (d) => DAYS[d])
    .replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/g, (m) => MONTHS[m])
    .replace(/\boff\b|\bclosed\b/g, 'выходной').replace(/(\d{2}:\d{2})-(\d{2}:\d{2})/g, '$1–$2').replace(/,\s*/g, ', ')
    .replace(/^(.)/, (x) => x.toUpperCase()));
}

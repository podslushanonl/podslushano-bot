import { useQuery } from '@tanstack/react-query';
import { parseArticle } from '@/features/handbook/parse';
import { PROVINCES, ProvinceId } from '@/lib/provinces';
import { BOT, getJson, SITE } from './client';
import { News } from './content';

// То, ради чего приложение открывают каждый день: новости на русском, вакансии и важные даты.

const decode = (s: string) => s.replace(/&#8211;|&ndash;/g, '–').replace(/&#8212;|&mdash;/g, '—').replace(/&#171;|&laquo;/g, '«')
  .replace(/&#187;|&raquo;/g, '»').replace(/&#8230;/g, '…').replace(/&nbsp;/g, ' ').replace(/&quot;/g, '"').replace(/&#0?39;|&#8217;/g, '’')
  .replace(/&amp;/g, '&').replace(/<[^>]+>/g, '').trim();

/** Слаг новости из ссылки: https://www.podslushano.nl/v-amsterdam-…/ → v-amsterdam-… */
export const newsSlug = (n: Pick<News, 'link'>) => n.link.replace(/\/+$/, '').split('/').pop() || '';

/** Новость целиком с сайта — показываем в приложении, без браузера. */
export const useNewsArticle = (slug: string) => useQuery({
  queryKey: ['news', slug], enabled: !!slug, staleTime: 3600_000,
  queryFn: async () => {
    const list = await getJson<any[]>(`${SITE}/wp-json/wp/v2/posts?slug=${encodeURIComponent(slug)}&_fields=id,title,content,link,date,_links,_embedded&_embed=wp:featuredmedia`);
    const p = list[0];
    if (!p) throw new Error('not found');
    return {
      title: decode(p.title?.rendered || ''), link: p.link as string, date: String(p.date || ''),
      img: (p._embedded?.['wp:featuredmedia']?.[0]?.source_url as string) || '',
      blocks: parseArticle(p.content?.rendered || ''),
    };
  },
});

// Провинция новости — по городу в заголовке («В Amsterdam…», «В Zeist…»): новости своей провинции идут первыми.
const CITIES: [RegExp, ProvinceId][] = PROVINCES.flatMap((p) => p.cities.map((c) => [
  new RegExp(`(^|[^\\p{L}])${c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/^['’]s-/, "['’]?s-")}([^\\p{L}]|$)`, 'iu'), p.id,
] as [RegExp, ProvinceId]));
export function newsProvince(title: string): ProvinceId | null {
  for (const [re, id] of CITIES) if (re.test(title)) return id;
  return null;
}

// ---------------------------------------------------------------- важные даты

export type NlDate = { date: string; end: string; title: string; nl: string; text: string; kind: 'holiday' | 'day' | 'clock' | 'deadline' | 'school'; region?: string };

/** Регион школьных каникул по провинции (Gelderland и Flevoland поделены — берём регион большей части). */
const SCHOOL: Record<ProvinceId, 'noord' | 'midden' | 'zuid'> = {
  gr: 'noord', fr: 'noord', dr: 'noord', ov: 'noord', fl: 'noord', nh: 'noord',
  ut: 'midden', zh: 'midden', ge: 'midden', ze: 'zuid', nb: 'zuid', li: 'zuid',
};
export const schoolRegion = (p: ProvinceId) => SCHOOL[p];

export const useNlDates = (p: ProvinceId | undefined) => useQuery({
  queryKey: ['nl-dates'], staleTime: 6 * 3600_000,
  queryFn: () => getJson<{ dates: NlDate[] }>(`${BOT}/api/app/dates.json`).then((d) => d.dates || []),
  select: (rows) => rows.filter((r) => r.kind !== 'school' || r.region === 'all' || !p || r.region === SCHOOL[p]),
});

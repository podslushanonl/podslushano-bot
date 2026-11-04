import { useQuery } from '@tanstack/react-query';
import { parseArticle } from '@/features/handbook/parse';
import { getJson, SITE } from './client';

// Справочник: подробные справки с сайта (рубрика «Справочник»). Их пишет и обновляет сервер
// по официальным источникам (utils/site_guides.py), приложение показывает их нативно.
const CATEGORY = 127;

export type GuideItem = { id: number; title: string; lead: string; date: string; link: string };

const decode = (s: string) => s
  .replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&#8230;|&hellip;/g, '…').replace(/&#8211;|&ndash;/g, '–')
  .replace(/&#8212;|&mdash;/g, '—').replace(/&#171;|&laquo;/g, '«').replace(/&#187;|&raquo;/g, '»').replace(/&#8217;/g, '’')
  .replace(/&quot;/g, '"').replace(/&#039;|&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
  .replace(/\s+/g, ' ').trim();
export { decode as decodeHtml };

export const useHandbook = () => useQuery({
  queryKey: ['handbook'], staleTime: 6 * 3600_000,
  queryFn: async () => {
    const d = await getJson<any[]>(`${SITE}/wp-json/wp/v2/posts?categories=${CATEGORY}&per_page=100&_fields=id,title,excerpt,date,link`);
    return d.map((p): GuideItem => ({ id: p.id, title: decode(p.title?.rendered || ''), lead: decode(p.excerpt?.rendered || ''), date: (p.date || '').slice(0, 10), link: p.link }));
  },
});

export const useArticle = (id: number) => useQuery({
  queryKey: ['handbook', id], staleTime: 24 * 3600_000, enabled: !!id,
  queryFn: async () => {
    const p = await getJson<any>(`${SITE}/wp-json/wp/v2/posts/${id}?_fields=id,title,content,link,modified`);
    return { id: p.id as number, title: decode(p.title?.rendered || ''), link: p.link as string, blocks: parseArticle(p.content?.rendered || '') };
  },
});

// Разделы справочника: статья попадает в первый раздел, чьё слово есть в заголовке.
export const SECTIONS: { key: string; title: string; icon: 'doc' | 'cross' | 'house' | 'briefcase' | 'wallet' | 'train' | 'child' | 'globe'; re: RegExp }[] = [
  { key: 'docs', title: 'Документы и статус', icon: 'doc', re: /BSN|DigiD|gemeente|BRP|гражданств|naturalis|inburgering|украинц|IND/i },
  { key: 'health', title: 'Здоровье', icon: 'cross', re: /huisarts|врач|медстрах|zorgverzeker|стоматолог/i },
  { key: 'home', title: 'Жильё', icon: 'house', re: /жиль|аренд|huur/i },
  { key: 'work', title: 'Работа и бизнес', icon: 'briefcase', re: /ZZP|KvK|BTW|WW|30%|работ|UWV/i },
  { key: 'money', title: 'Налоги, пособия и деньги', icon: 'wallet', re: /belasting|налог|toeslag|kinderbijslag|пособи|счёт|банк/i },
  { key: 'kids', title: 'Дети и школа', icon: 'child', re: /школ|ребён|детск|kinderopvang/i },
  { key: 'transport', title: 'Транспорт', icon: 'train', re: /OV-chip|транспорт|водительск|права|поезд/i },
];
export const OTHER = { key: 'other', title: 'Другое', icon: 'globe' as const };
export const sectionOf = (title: string) => SECTIONS.find((s) => s.re.test(title)) || OTHER;

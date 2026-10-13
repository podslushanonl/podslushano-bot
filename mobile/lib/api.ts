// Данные приложения: контент сайта (WordPress) и сервисы бота (поезда NS, «Сэкономить»)
export const SITE = 'https://www.podslushano.nl';
export const BOT = 'https://worker-production-ad76.up.railway.app';
export const TG_BOT = 'https://t.me/podslushano_nl_bot';

export type News = { id: string; link: string; date: string; time: string; cat: string; h: string; lead: string; img: string; thumb: string };
export type EventItem = {
  key: string; h: string; s?: string; date: string; time?: string; end?: string; venue?: string; addr?: string;
  city?: string; price?: string; img?: string; url?: string; cat?: string; p?: string[]; tickets?: string[][]; partner?: boolean;
};
export type Job = { id: string; title: string; company?: string; city?: string; lang?: string; type?: string; salary?: string; posted?: string; about?: string; url?: string };
export type AppData = { news: News[]; events: EventItem[]; jobs: Job[] };

async function json<T>(url: string): Promise<T> {
  const r = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json() as Promise<T>;
}

const strip = (html: string) =>
  html.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&#8230;/g, '…').replace(/&#8211;/g, '–')
    .replace(/&#8212;/g, '—').replace(/&#171;/g, '«').replace(/&#187;/g, '»').replace(/&amp;/g, '&').trim();

/** Весь контент одним запросом; пока на сайте нет /pn/v1/app — новости из стандартного API WordPress. */
export async function loadApp(): Promise<AppData> {
  try {
    const d = await json<AppData>(`${SITE}/wp-json/pn/v1/app`);
    return { news: d.news || [], events: d.events || [], jobs: d.jobs || [] };
  } catch {
    const posts = await json<any[]>(`${SITE}/wp-json/wp/v2/posts?per_page=20&_embed=wp:featuredmedia`);
    return {
      news: posts.map((p) => ({
        id: String(p.id), link: p.link, date: (p.date || '').slice(0, 10), time: (p.date || '').slice(11, 16), cat: 'Новости',
        h: strip(p.title?.rendered || ''), lead: strip(p.excerpt?.rendered || ''),
        img: p._embedded?.['wp:featuredmedia']?.[0]?.source_url || '', thumb: '',
      })),
      events: [], jobs: [],
    };
  }
}

export type Departure = { direction: string; time: string; delay: number; track: string; track_changed: boolean; category: string; cancelled: boolean; via?: string[] };
export type Disruption = { id: string; type: string; type_ru: string; title: string; active: boolean; stations: string[]; text?: string; situation?: string; cause?: string; advice?: string[]; start_ru?: string; end_ru?: string; expected?: string };

export const departures = (code: string) => json<{ departures: Departure[] }>(`${BOT}/api/ns/departures?station=${encodeURIComponent(code)}&limit=12`).then((d) => d.departures || []);
export const disruptions = () => json<{ now: Disruption[]; planned: Disruption[] }>(`${BOT}/api/ns/disruptions`);
export const stations = () => json<{ stations: [string, string][] }>(`${BOT}/api/ns/stations`).then((d) => d.stations || []);

/** Ссылка «Сэкономить» через счётчик переходов бота (метка источника — app). */
export const goUrl = (key: string) => `${BOT}/go/${key}?s=app`;

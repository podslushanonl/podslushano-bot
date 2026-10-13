import { useQuery } from '@tanstack/react-query';
import { BOT, getJson, SITE } from './client';

export type News = { id: string; link: string; date: string; time: string; cat: string; h: string; lead: string; img: string; thumb: string };
export type EventItem = {
  key: string; h: string; s?: string; date: string; time?: string; end?: string; venue?: string; addr?: string;
  city?: string; price?: string; img?: string; url?: string; cat?: string; p?: string[]; tickets?: string[][]; partner?: boolean;
};
export type Job = { id: string; title: string; company?: string; city?: string; lang?: string; type?: string; salary?: string; posted?: string; about?: string; url?: string };
export type Content = { news: News[]; events: EventItem[]; jobs: Job[] };

const strip = (html: string) =>
  html.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&#8230;/g, '…').replace(/&#8211;/g, '–')
    .replace(/&#8212;/g, '—').replace(/&#171;/g, '«').replace(/&#187;/g, '»').replace(/&amp;/g, '&').trim();

async function loadContent(): Promise<Content> {
  try {
    const d = await getJson<Content>(`${SITE}/wp-json/pn/v1/app`);
    return { news: d.news || [], events: d.events || [], jobs: d.jobs || [] };
  } catch {
    const posts = await getJson<any[]>(`${SITE}/wp-json/wp/v2/posts?per_page=20&_embed=wp:featuredmedia`);
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

/** Новости, афиша и вакансии с сайта — один общий запрос на все экраны. */
export const useContent = () => useQuery({ queryKey: ['content'], queryFn: loadContent, staleTime: 5 * 60_000 });

// ---------------------------------------------------------------- погода (Open-Meteo, без ключа)

export const CITY_COORDS: Record<string, [number, number]> = {
  Amsterdam: [52.37, 4.9], Rotterdam: [51.92, 4.48], 'Den Haag': [52.08, 4.31], Utrecht: [52.09, 5.12],
  Eindhoven: [51.44, 5.47], Groningen: [53.22, 6.57], Tilburg: [51.56, 5.09], Almere: [52.35, 5.26],
  Breda: [51.59, 4.78], Nijmegen: [51.84, 5.86], Arnhem: [51.98, 5.91], Haarlem: [52.38, 4.64],
  Leiden: [52.16, 4.49], Maastricht: [50.85, 5.69], Zwolle: [52.52, 6.08], Amersfoort: [52.16, 5.39],
  Delft: [52.01, 4.36], Enschede: [52.22, 6.89], 'Den Bosch': [51.69, 5.3], Oss: [51.76, 5.52],
};

export type Weather = { temp: number; code: number; rainSoon: string | null; wind: number };

const WMO: [number[], string][] = [
  [[0], 'Ясно'], [[1, 2], 'Переменная облачность'], [[3], 'Пасмурно'], [[45, 48], 'Туман'],
  [[51, 53, 55, 56, 57], 'Морось'], [[61, 63, 65, 66, 67, 80, 81, 82], 'Дождь'], [[71, 73, 75, 77, 85, 86], 'Снег'], [[95, 96, 99], 'Гроза'],
];
export const weatherText = (code: number) => WMO.find(([c]) => c.includes(code))?.[1] || '';
export const weatherIcon = (code: number) => (code === 0 || code === 1 ? 'sun' : code >= 51 ? 'rain' : 'cloud') as 'sun' | 'rain' | 'cloud';

async function loadWeather(city: string): Promise<Weather> {
  const [lat, lon] = CITY_COORDS[city] || CITY_COORDS.Utrecht;
  const d = await getJson<any>(`https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}` +
    '&current=temperature_2m,weather_code,wind_speed_10m&hourly=precipitation_probability&forecast_hours=12&timezone=Europe%2FAmsterdam');
  const probs: number[] = d.hourly?.precipitation_probability || [];
  const times: string[] = d.hourly?.time || [];
  const i = probs.findIndex((p) => p >= 60);
  return {
    temp: Math.round(d.current?.temperature_2m ?? 0), code: d.current?.weather_code ?? 3,
    wind: Math.round(d.current?.wind_speed_10m ?? 0), rainSoon: i >= 0 ? (times[i] || '').slice(11, 16) : null,
  };
}

export const useWeather = (city: string) => useQuery({ queryKey: ['weather', city], queryFn: () => loadWeather(city), staleTime: 15 * 60_000 });

// ---------------------------------------------------------------- поезда NS

export type Departure = { direction: string; time: string; delay: number; track: string; track_changed: boolean; category: string; cancelled: boolean; via?: string[] };
export type Disruption = { id: string; type: string; type_ru: string; title: string; active: boolean; stations: string[]; text?: string; situation?: string; cause?: string; advice?: string[]; start_ru?: string; end_ru?: string; expected?: string };

export const useDisruptions = () => useQuery({
  queryKey: ['ns', 'disruptions'], staleTime: 2 * 60_000, refetchInterval: 5 * 60_000,
  queryFn: () => getJson<{ now: Disruption[]; planned: Disruption[] }>(`${BOT}/api/ns/disruptions`),
});
export const useDepartures = (code: string) => useQuery({
  queryKey: ['ns', 'dep', code], enabled: !!code, staleTime: 30_000, refetchInterval: 60_000,
  queryFn: () => getJson<{ departures: Departure[] }>(`${BOT}/api/ns/departures?station=${encodeURIComponent(code)}&limit=15`).then((d) => d.departures || []),
});
export const useStations = () => useQuery({
  queryKey: ['ns', 'stations'], staleTime: 24 * 3600_000,
  queryFn: () => getJson<{ stations: [string, string][] }>(`${BOT}/api/ns/stations`).then((d) => d.stations || []),
});

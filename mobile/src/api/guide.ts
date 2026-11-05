import { useQuery } from '@tanstack/react-query';
import { BOT, getJson } from './client';

// Контакт-гайд: русскоязычные специалисты с сервера (/api/specialists.json).
export type SpecialistLink = { type: string; label: string; url: string };
export type Specialist = {
  id: number; slug: string; name: string; category: string; city: string; province: string;
  online: boolean; premium: boolean; description: string; contact: string; links: SpecialistLink[]; photo?: string | null;
};

/** Убирает эмодзи и лишние пробелы: в приложении только текст и настоящие иконки. */
export const clean = (s: string) =>
  (s || '').replace(/[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{1F3FB}-\u{1F3FF}\u{FE0F}\u{200D}\u{20E3}]/gu, '').replace(/\s{2,}/g, ' ').trim();

async function load(): Promise<Specialist[]> {
  const d = await getJson<{ specialists: Specialist[] }>(`${BOT}/api/specialists.json`);
  return (d.specialists || []).map((s) => ({
    ...s, name: clean(s.name), description: clean(s.description), category: clean(s.category),
    links: (s.links || []).map((l) => ({ ...l, label: clean(l.label) })),
  }));
}

export const useSpecialists = () => useQuery({ queryKey: ['specialists'], queryFn: load, staleTime: 30 * 60_000 });

/** Категория с заглавной буквы для заголовков и чипов. */
export const catTitle = (c: string) => (c ? c[0].toUpperCase() + c.slice(1) : c);

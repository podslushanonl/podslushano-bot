import { useMemo } from 'react';
import { EventItem, useContent } from '@/api/content';
import { provinceOfCity, ProvinceId } from '@/lib/provinces';

const todayIso = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Europe/Amsterdam' });

/** Предстоящие события только выбранной провинции, по дате. */
export function useProvinceEvents(pid: ProvinceId | undefined) {
  const q = useContent();
  const today = todayIso();
  const events = useMemo<EventItem[]>(() => (q.data?.events || [])
    .filter((e) => (e.end || e.date) >= today && pid && provinceOfCity(e.city) === pid)
    .sort((a, b) => (a.date + (a.time || '')).localeCompare(b.date + (b.time || ''))), [q.data, today, pid]);
  return { ...q, events, today };
}

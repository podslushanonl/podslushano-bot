/** «В сети» / «Был(а) в сети …» по данным сервера (online, last_seen в UTC). */
export type Presence = { online?: boolean; last_seen?: string };

export function presenceLabel(p?: Presence): string {
  if (!p) return '';
  if (p.online) return 'В сети';
  if (!p.last_seen) return '';
  const d = new Date(p.last_seen);
  const min = Math.round((Date.now() - d.getTime()) / 60000);
  if (min < 60) return `Был(а) в сети ${Math.max(1, min)} мин назад`;
  const hm = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Amsterdam' });
  const day = (x: Date) => x.toLocaleDateString('ru-RU', { timeZone: 'Europe/Amsterdam' });
  const now = new Date();
  const yesterday = new Date(now.getTime() - 86400000);
  if (day(d) === day(now)) return `Был(а) в сети сегодня в ${hm}`;
  if (day(d) === day(yesterday)) return `Был(а) в сети вчера в ${hm}`;
  return `Был(а) в сети ${d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', timeZone: 'Europe/Amsterdam' })}`;
}

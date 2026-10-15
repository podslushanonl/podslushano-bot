import type { FlagCode } from '@/ui';

/** Страны входа по номеру: код, группы цифр для маски и пример номера. */
export type PhoneCountry = { flag: FlagCode; name: string; cc: string; groups: number[]; min: number; sample: string };

export const COUNTRIES: PhoneCountry[] = [
  { flag: 'NL', name: 'Нидерланды', cc: '31', groups: [1, 2, 2, 2, 2], min: 9, sample: '6 12 34 56 78' },
  { flag: 'DE', name: 'Германия', cc: '49', groups: [3, 4, 4], min: 10, sample: '151 2345 6789' },
  { flag: 'BE', name: 'Бельгия', cc: '32', groups: [3, 2, 2, 2], min: 9, sample: '470 12 34 56' },
];

const maxLen = (c: PhoneCountry) => c.groups.reduce((a, b) => a + b, 0);

/** Только цифры национального номера: без ведущего 0 (06… → 6…) и не длиннее, чем бывает. */
export function phoneDigits(raw: string, c: PhoneCountry) {
  return raw.replace(/\D/g, '').replace(/^0+/, '').slice(0, maxLen(c));
}

/** Ввод или вставка номера. Полный номер (+49…, 0049…, 31612345678) сам выбирает страну и теряет её код. */
export function parsePhone(raw: string, current: PhoneCountry): { country: PhoneCountry; digits: string } {
  const all = raw.replace(/\D/g, '');
  const intl = raw.trim().startsWith('+') ? all : all.startsWith('00') ? all.slice(2) : '';
  const byCode = (d: string) => COUNTRIES.find((x) => d.startsWith(x.cc));
  const full = intl ? byCode(intl) : all.length > maxLen(current) && all.startsWith(current.cc) ? current : undefined;
  if (full) return { country: full, digits: phoneDigits((intl || all).slice(full.cc.length), full) };
  return { country: current, digits: phoneDigits(raw, current) };
}

/** 612345678 → «6 12 34 56 78» по группам страны. */
export function formatPhone(digits: string, c: PhoneCountry) {
  const out: string[] = [];
  let i = 0;
  for (const g of c.groups) {
    if (i >= digits.length) break;
    out.push(digits.slice(i, i + g));
    i += g;
  }
  return out.join(' ');
}

export const phoneReady = (digits: string, c: PhoneCountry) => digits.length >= c.min;

/** +31612345678 → «+31 6 12 34 56 78» (для экрана кода). */
export function prettyPhone(e164: string) {
  const c = [...COUNTRIES].sort((a, b) => b.cc.length - a.cc.length).find((x) => e164.startsWith('+' + x.cc));
  return c ? `+${c.cc} ${formatPhone(e164.slice(c.cc.length + 1), c)}` : e164;
}

const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const MONTHS_NOM = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
const WD = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

const parse = (d: string) => { const [y, m, day] = d.split('-').map(Number); return new Date(y, (m || 1) - 1, day || 1); };

export function dayMonth(d: string) {
  if (!d) return '';
  const x = parse(d);
  return `${x.getDate()} ${MONTHS[x.getMonth()]}`;
}
export function weekday(d: string) { return d ? WD[parse(d).getDay()] : ''; }
export function monthTitle(d: string) { const x = parse(d); return `${MONTHS_NOM[x.getMonth()]} ${x.getFullYear()}`; }
export function ago(date: string, time = '') {
  if (!date) return '';
  const today = new Date();
  const iso = (x: Date) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  const y = new Date(today); y.setDate(today.getDate() - 1);
  if (date === iso(today)) return time ? `сегодня, ${time}` : 'сегодня';
  if (date === iso(y)) return time ? `вчера, ${time}` : 'вчера';
  return dayMonth(date);
}

/** Русское склонение: plural(5, ['лайк', 'лайка', 'лайков']) → «лайков». */
export function plural(n: number, [one, few, many]: [string, string, string]) {
  const a = Math.abs(n) % 100, b = a % 10;
  return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many;
}

/** «только что», «5 минут назад», «3 часа назад», «вчера», «4 дня назад», иначе «12 октября». */
export function relTime(iso: string) {
  const t = Date.parse(iso);
  if (!t) return '';
  const min = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (min < 1) return 'только что';
  if (min < 60) return `${min} ${plural(min, ['минуту', 'минуты', 'минут'])} назад`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} ${plural(h, ['час', 'часа', 'часов'])} назад`;
  const d = Math.round(h / 24);
  if (d === 1) return 'вчера';
  if (d < 7) return `${d} ${plural(d, ['день', 'дня', 'дней'])} назад`;
  return dayMonth(new Date(t).toISOString().slice(0, 10));
}

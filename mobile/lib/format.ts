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

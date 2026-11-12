// ТЕСТОВЫЕ ДАННЫЕ ЭТАПА 1. Здесь только то, чего ещё нет на сервере; всё остальное (новости, афиша,
// специалисты, погода, поезда) приложение уже берёт из настоящих источников.
// Каждая запись заменяется на запрос к API на этапе, указанном в комментарии.

/** Счётчик «Пойду» у события: пока считается из ключа, чтобы числа не прыгали (этап 2: GET /api/app/event/{key}/going). */
export function mockGoing(key: string) {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) % 997;
  return 3 + (h % 58);
}

/** Встречи сообщества, если сервер прогулок allo.walks пока не отдал ни одной (этап 2). */
export const MOCK_MEETINGS = [
  { key: 'm1', title: 'Прогулка по каналам и кофе', place: 'Amsterdam', when: 'сб, 14 ноября, 12:00', price: '€12,00', left: 6 },
  { key: 'm2', title: 'Настольные игры на русском', place: 'Utrecht', when: 'вс, 15 ноября, 15:00', price: 'Бесплатно', left: 11 },
  { key: 'm3', title: 'Поход по дюнам Kennemerland', place: 'Haarlem', when: 'сб, 21 ноября, 10:30', price: '€15,00', left: 4 },
];

/** Статьи раздела «Сэкономить» (этап 3: рубрика сайта). */
export const MOCK_SAVE = [
  { id: 's1', tag: 'Транспорт', title: 'Скидка 40% на поезда NS: как работает Dal Voordeel', mins: 4 },
  { id: 's2', tag: 'Продукты', title: 'Too Good To Go, bonus-карты и рынки: еда вдвое дешевле', mins: 6 },
  { id: 's3', tag: 'Налоги', title: 'Какие пособия (toeslagen) вам положены и как их оформить', mins: 7 },
  { id: 's4', tag: 'Дом', title: 'Энергия зимой: как выбрать контракт и не переплатить', mins: 5 },
];

/** Размещения в «Кабинете бизнеса» (этап 5: GET /api/app/business/items). */
export type BusinessItem = {
  id: string; kind: 'event' | 'card'; title: string; status: 'active' | 'pending' | 'draft';
  until?: string; views: number; clicks: number;
};
export const MOCK_BUSINESS: BusinessItem[] = [
  { id: 'b1', kind: 'card', title: 'Бухгалтер для ZZP · Anna Finance', status: 'active', until: '2026-12-11', views: 412, clicks: 37 },
  { id: 'b2', kind: 'event', title: 'Стендап на русском в Rotterdam', status: 'pending', views: 0, clicks: 0 },
  { id: 'b3', kind: 'event', title: 'Мастер-класс по керамике', status: 'draft', views: 0, clicks: 0 },
];

# Структура приложения podslushano.nl (версия 3, только iOS и Android)

Стек: Expo, TypeScript, Expo Router, TanStack Query, Reanimated, expo-image, expo-notifications,
expo-haptics, expo-web-browser, @gorhom/bottom-sheet. Веб-версия не выпускается.

## Навигация
Нижнее меню (`src/features/nav/AppTabs.tsx`): Лента — События — [+] — Гид — Профиль.
Кнопка «+» открывает шторку `CreateSheet` (событие €9,99, карточка €9,99, новость бесплатно).
Гостевой режим: разделы открыты сразу; вход просится только на целевом действии.
Deep links: схема `podslushano://` (например, `podslushano://payment-success?id=…`).

```
src/
  app/
    _layout.tsx            корневой стек, тема, провайдер шторок
    (tabs)/
      _layout.tsx          нижнее меню
      index.tsx            Лента: «Нидерланды сейчас», главное за неделю, новости, «Сэкономить»
      events.tsx           События: Афиша | Встречи, фильтр городов
      guide.tsx            Гид: поиск, плитки сервисов, КонтактGuide
      profile.tsx          Профиль: город и станция, избранное, кабинет бизнеса
    create/[kind].tsx      создание из «+»: event | card | suggest (формы — этап 5)
    payment-success.tsx    возврат из оплаты Mollie
    business.tsx           кабинет бизнеса (тестовые данные до этапа 5)
    save.tsx               «Сэкономить» (тестовые данные до этапа 3)
    handbook/              справочник: список и статья
    event/[key].tsx, specialist/[id].tsx, news/, trains.tsx, jobs.tsx, dates.tsx,
    places.tsx, place/[id].tsx, shop/, province.tsx, search.tsx, login.tsx …
  theme/tokens.ts          цвета Light/Dark, сетка 8pt, скругления, типографика (системные шрифты)
  ui/                      Button, Card, Chip, Segmented, Skeleton, EmptyState, BottomSheetWrapper, Field, Icon …
  features/                блоки экранов: nav, create, afisha, guide, news, daily, province, push …
  api/                     запросы к серверу и сайту (TanStack Query)
  lib/                     город и провинция, станция, уведомления, форматы
  mocks/                   тестовые данные для того, чего ещё нет на сервере
```

## Дизайн-система
- Цвета: `bg` (background), `bgElevated` (surface), `accent` (primary #FF5A1F), `secondary` (#0066CC),
  `ink` (textPrimary), `muted` (textSecondary), `line` (border 1px), `success`, `danger`.
- Отступ экрана 16, между карточками 12; скругления: карточки 16, кнопки и поля 12, чипы 999.
- Зона нажатия не меньше 44×44; лёгкая вибрация на вкладках, фильтрах и кнопках.
- Загрузка — скелетоны; пустые экраны — `EmptyState` с кнопкой действия.

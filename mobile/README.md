# podslushano.nl — мобильное приложение

Expo (React Native), один код для iPhone, Android и браузера. Всё в приложении относится
к выбранной провинции; структура разделов описана в `docs/STRUCTURE.md`, бренд — в `../brand/README.md`.

## Разделы

| Раздел | Откуда данные |
|---|---|
| Сегодня | погода Open-Meteo, события провинции, поезда NS (сервер), подборка мест |
| Афиша | сайт `/wp-json/pn/v1/app` (у события есть `province`), прогулки allo.walks `/api/allo/v2/events` |
| Места | `src/data/places.json` — собирается `tools/build_places.py` из Wikidata (CC0), фото Wikimedia Commons |
| Гид | контакт-гайд `/api/specialists.json`, справочник — рубрика «Справочник» сайта |
| Магазин | `/api/shop/*` на сервере, каталог `../data/shop/catalog.json`, оплата Mollie |
| Профиль | вход по SMS или почте `/api/app/auth/*`, уведомления `/api/app/push/*`, удаление аккаунта |

Справочник городов и провинций — `src/lib/provinces.ts`. Для сайта из него собирается
`../wordpress/theme/podslushano-2026/inc/provinces.php`: `python3 tools/gen_provinces_php.py` из корня репозитория.

## Запуск

```bash
cd mobile
npm install
npx expo start          # QR-код; push-уведомления и вход через Telegram — только в development build
npx expo start --web    # в браузере
```

Проверки перед коммитом: `npx tsc --noEmit`, `npx expo lint`, `npx expo-doctor`.

## Данные мест

```bash
python3 tools/build_places.py   # около 8 минут: Wikidata ограничивает частоту запросов
```
Ответы сохраняются в `tools/.places-cache/`, повторный запуск продолжает с места остановки.

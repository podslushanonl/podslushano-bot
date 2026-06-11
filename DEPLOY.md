# Как запустить бота 24/7

Бот работает на «long-polling»: его процесс должен крутиться **постоянно**.
Значит, нужен компьютер, который не выключается. Варианты — от самого простого
к более ручному:

| Способ | Кому подойдёт | Стоимость |
|--------|---------------|-----------|
| **A. VPS + Docker** (рекомендую) | надёжно, копипаст команд | ~4–5 €/мес за VPS |
| B. VPS + systemd | если не хочешь Docker | ~4–5 €/мес за VPS |
| C. Railway / Render | без своего сервера | от ~5 $/мес |

Что нужно в любом случае:

1. **Токен бота** — получи у [@BotFather](https://t.me/BotFather): команда `/newbot`,
   придумай имя → он выдаст строку вида `123456789:AA...`.
2. **Свой Telegram ID** — напиши боту [@userinfobot](https://t.me/userinfobot),
   он пришлёт число (это твой `ADMIN_IDS` — туда бот шлёт заявки на модерацию).

---

## A. VPS + Docker (рекомендуемый способ)

VPS — это арендованный сервер, который работает круглосуточно. Подойдёт самый
дешёвый (1 ГБ памяти хватает с запасом): Hetzner, Timeweb, Beget, DigitalOcean и т.п.
Бери образ **Ubuntu 22.04/24.04**.

### Шаг 1. Зайти на сервер
После создания VPS провайдер даёт IP и пароль. С твоего компьютера в терминале:
```bash
ssh root@IP_СЕРВЕРА
```

### Шаг 2. Установить Docker (один раз)
```bash
curl -fsSL https://get.docker.com | sh
```

### Шаг 3. Скачать код бота
```bash
apt update && apt install -y git
git clone https://github.com/podslushanonl/podslushano-bot.git
cd podslushano-bot
```

### Шаг 4. Создать файл с секретами `.env`
```bash
cp .env.example .env
nano .env
```
Впиши свои значения (стрелками подвинь курсор, замени текст):
```
BOT_TOKEN=сюда_токен_от_BotFather
ADMIN_IDS=сюда_твой_id_от_userinfobot
GUIDE_URL=https://www.podslushano.nl/contact-directory-netherlands/
```
Сохрани: `Ctrl+O`, `Enter`, затем выйди: `Ctrl+X`.

### Шаг 5. Запустить
```bash
docker compose up -d --build
```
Готово! Бот работает и сам перезапустится при сбое или перезагрузке сервера.

### Полезные команды
```bash
docker compose logs -f      # смотреть логи (выход — Ctrl+C)
docker compose restart      # перезапустить
docker compose down         # остановить
git pull && docker compose up -d --build   # обновить после изменений в коде
```

---

## B. VPS + systemd (без Docker)

Если не хочешь Docker — есть готовый юнит `deploy/podslushano-bot.service`.

```bash
# код в /opt
git clone https://github.com/podslushanonl/podslushano-bot.git /opt/podslushano-bot
cd /opt/podslushano-bot
cp .env.example .env && nano .env      # впиши токен и ADMIN_IDS (как в способе A)

# окружение Python
apt update && apt install -y python3-venv
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# служба
cp deploy/podslushano-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now podslushano-bot
```
Логи: `journalctl -u podslushano-bot -f`. Перезапуск: `systemctl restart podslushano-bot`.

---

## C. Railway / Render (без своего сервера)

Подходит, если не хочешь возиться с сервером. Запускать бота нужно как
**Background Worker** (не Web Service — у бота нет веб-страницы), команда запуска:
`python bot.py`.

Важные моменты:
- Переменные `BOT_TOKEN`, `ADMIN_IDS`, `GUIDE_URL` задаются в веб-панели сервиса
  (раздел Variables / Environment) — файл `.env` туда не нужен.
- База `data/bot.db` лежит в файловой системе. На таких платформах диск
  обнуляется при каждом передеплое, поэтому **подключи постоянный диск (Volume)**
  и смонтируй его в `/app/data` — иначе после обновления потеряются заявки
  пользователей (специалисты-то зальются заново из `data/specialists_seed.py`).

---

## Проверка, что всё работает

1. Открой своего бота в Telegram, нажми **/start**.
2. Нажми кнопку поиска контактов и напиши, например: *«нужен фотограф в Амстердаме»* —
   бот должен вернуть реальных специалистов из гайда.
3. Заявки на модерацию приходят в личку тому, чей ID указан в `ADMIN_IDS`.

## Обновление списка специалистов

Сейчас 287 контактов «вшиты» в `data/specialists_seed.py`, и они заливаются в базу
**только один раз** — при первом запуске на пустой базе. Если позже список на сайте
поменяется и нужно будет обновить базу — напиши мне, я сделаю скрипт синхронизации
(вариант №2 из нашего плана).

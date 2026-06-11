# Образ для телеграм-бота Подслушано.nl
FROM python:3.11-slim

# Не пишем .pyc и не буферизуем вывод (логи видны сразу)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Сначала зависимости — чтобы слой кэшировался и пересборка была быстрой
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем код
COPY . .

# Папка для базы SQLite (её монтируем томом в docker-compose, чтобы данные жили)
RUN mkdir -p data

CMD ["python", "bot.py"]

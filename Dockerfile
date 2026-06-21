# Образ для телеграм-бота Подслушано.nl
FROM python:3.11-slim

# Не пишем .pyc и не буферизуем вывод (логи видны сразу)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ffmpeg нужен для видео-кружков (video note) в канал
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Сначала зависимости — чтобы слой кэшировался и пересборка была быстрой
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем код
COPY . .

# Папка для базы SQLite (её монтируем томом в docker-compose, чтобы данные жили)
RUN mkdir -p data

CMD ["python", "bot.py"]

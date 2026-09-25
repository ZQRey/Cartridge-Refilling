FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей (включая библиотеки для работы ldap3 при необходимости)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libldap2-dev \
    libsasl2-dev \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создание директории для монтирования тома базы данных
RUN mkdir -p /data

EXPOSE 8000

ENV DATABASE_URL="sqlite:////data/cartridges.db"
ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11-slim

# Dependencias completas para Chromium en Debian Trixie
RUN apt-get update && apt-get install -y \
    wget curl unzip \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libx11-6 libxcb1 \
    libxext6 libx11-xcb1 libxss1 libxtst6 \
    fonts-liberation fonts-noto-color-emoji \
    xdg-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar Chromium sin install-deps (ya instalamos las deps arriba)
RUN playwright install chromium

COPY . .

RUN mkdir -p logs screenshots data

CMD ["python3", "main.py"]

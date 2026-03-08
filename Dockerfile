FROM python:3.11-slim

# Dependencias del sistema para Playwright/Chromium
RUN apt-get update && apt-get install -y \
    wget curl unzip \
    libglib2.0-0 libnss3 libnspr4 libdbus-1-3 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    fonts-liberation xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar Playwright y Chromium
RUN playwright install chromium
RUN playwright install-deps chromium

# Copiar código del proyecto
COPY . .

# Crear directorios necesarios
RUN mkdir -p logs screenshots data

CMD ["python3", "main.py"]

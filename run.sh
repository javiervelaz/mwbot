#!/bin/bash
# Script de arranque rápido

set -e

echo "🤖 Microworkers Bot"
echo "==================="

# Verificar que existe .env
if [ ! -f .env ]; then
    echo "❌ No se encontró .env — creando plantilla..."
    cat > .env << 'ENV'
MW_EMAIL=javiervelaz@hotmail.com
MW_PASSWORD=*Javier0
HEADLESS=true
MIN_PAGO=0.05
MAX_TAREAS_DIA=50
DELAY_MIN=5
DELAY_MAX=20
ENV
    echo "✏️  Editá .env con tus credenciales y volvé a correr."
    exit 1
fi

# Modo de ejecución
MODE=${1:-docker}

if [ "$MODE" = "docker" ]; then
    echo "▶ Modo: Docker"
    docker compose up -d --build
    echo "✅ Bot corriendo en background"
    echo "   Ver logs:    docker logs -f mwbot"
    echo "   Detener:     docker compose down"

elif [ "$MODE" = "local" ]; then
    echo "▶ Modo: Local (venv)"
    if [ ! -d venv ]; then
        python3 -m venv venv
        source venv/bin/activate
        pip install -r requirements.txt
        playwright install chromium
        playwright install-deps chromium
    else
        source venv/bin/activate
    fi
    python3 main.py

elif [ "$MODE" = "stop" ]; then
    docker compose down
    echo "✅ Bot detenido"

elif [ "$MODE" = "logs" ]; then
    docker logs -f mwbot

elif [ "$MODE" = "status" ]; then
    docker ps | grep mwbot || echo "Bot no está corriendo"

else
    echo "Uso: ./run.sh [docker|local|stop|logs|status]"
fi

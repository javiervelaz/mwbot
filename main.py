import asyncio
import random
import os
import sys
from dotenv import load_dotenv
from loguru import logger
from playwright.async_api import async_playwright

from modules.database import (
    init_db, depurar_db, guardar_sesion, resumen_ganancias,
    limpiar_tareas_procesadas, reset_db_total
)
from modules.auth import login, verificar_sesion_activa
from modules.scraper import obtener_tareas
from modules.executor import ejecutar_tarea
from modules.stealth import crear_contexto_stealth, aplicar_stealth

load_dotenv()

logger.add(
    "logs/bot_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="7 days",
    level="INFO"
)

async def correr_sesion():
    headless  = os.getenv("HEADLESS", "false").lower() == "true"
    max_tareas = int(os.getenv("MAX_TAREAS_DIA", "50"))
    min_pago   = float(os.getenv("MIN_PAGO", "0.05"))
    delay_min  = int(os.getenv("DELAY_MIN", "5"))
    delay_max  = int(os.getenv("DELAY_MAX", "20"))
    max_intentos_factor = int(os.getenv("MAX_INTENTOS_FACTOR", "3"))
    enable_ttv = true

    logger.info("=" * 50)
    logger.info("🤖 Iniciando sesión del bot Microworkers")
    logger.info(f"Config: headless={headless} | max_tareas={max_tareas} | min_pago=${min_pago} | ttv={enable_ttv}")
    logger.info("=" * 50)

    tareas_completadas = 0
    ganancias_sesion = 0.0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ]
        )

        try:
            context = await crear_contexto_stealth(browser)
            page = await context.new_page()
            await aplicar_stealth(page)

            logueado = await login(page)
            if not logueado:
                logger.error("No se pudo hacer login. Abortando sesión.")
                return

            tareas = await obtener_tareas(page, min_pago=min_pago)

            if not tareas:
                logger.warning("No hay tareas automatizables disponibles.")
                return

            max_intentos = min(len(tareas), max_tareas * max_intentos_factor)
            logger.info(
                f"Objetivo: completar hasta {max_tareas} tareas "
                f"(máx intentos={max_intentos}, factor={max_intentos_factor})"
            )

            intentos = 0
            for tarea in tareas:
                if tareas_completadas >= max_tareas:
                    logger.info("Objetivo de tareas completadas alcanzado")
                    break
                if intentos >= max_intentos:
                    logger.info("Se alcanzó el máximo de intentos configurado para la sesión")
                    break

                intentos += 1
                logger.info(f"\n--- Intento {intentos} de {max_intentos} ---")

                if intentos > 1 and intentos % 10 == 0:
                    sesion_ok = await verificar_sesion_activa(page)
                    if not sesion_ok:
                        logger.warning("Sesión expirada, reintentando login...")
                        logueado = await login(page)
                        if not logueado:
                            logger.error("No se pudo renovar la sesión. Terminando.")
                            break

                exito = await ejecutar_tarea(page, tarea)

                if exito:
                    tareas_completadas += 1
                    ganancias_sesion += tarea.pago

                pausa = random.uniform(delay_min, delay_max)
                logger.info(f"Pausa de {pausa:.1f}s antes de la siguiente tarea...")
                await asyncio.sleep(pausa)

        except Exception as e:
            logger.error(f"Error inesperado en la sesión: {e}")

        finally:
            try:
                await browser.close()
            except Exception:
                pass  # browser ya estaba cerrado/muerto

    guardar_sesion(tareas_completadas, ganancias_sesion)
    resumen = resumen_ganancias()
    logger.info("=" * 50)
    logger.info(f"✅ Sesión finalizada")
    logger.info(f"   Tareas completadas: {tareas_completadas}")
    logger.info(f"   Ganado esta sesión: ${ganancias_sesion:.2f}")
    logger.info(f"   Ganado hoy:         ${resumen['hoy']:.2f}")
    logger.info(f"   Ganado total:       ${resumen['total']:.2f}")
    logger.info("=" * 50)


async def main():
    init_db()

    if os.getenv("RESET_DB_TOTAL_AL_INICIO", "false").lower() == "true":
        reset_db_total()
    elif os.getenv("RESET_TAREAS_AL_INICIO", "false").lower() == "true":
        limpiar_tareas_procesadas()

    depurar_db()  # ← limpia pendientes atascadas al arrancar

    logger.info("Bot iniciado en modo 24/7")

    while True:
        try:
            await correr_sesion()
        except Exception as e:
            logger.error(f"Error en sesión principal: {e}")

        descanso = random.uniform(30 * 60, 90 * 60)
        logger.info(f"Descansando {descanso/60:.1f} minutos hasta la próxima sesión...")
        await asyncio.sleep(descanso)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("clean-processed", "reset-db"):
        init_db()
        if sys.argv[1] == "clean-processed":
            limpiar_tareas_procesadas()
        else:
            reset_db_total()
    else:
        asyncio.run(main())

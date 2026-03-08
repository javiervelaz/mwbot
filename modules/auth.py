import os
import asyncio
import random
from dotenv import load_dotenv
from loguru import logger
from playwright.async_api import Page

load_dotenv()

async def login(page: Page) -> bool:
    """
    Hace login en Microworkers.
    Usa email y password del archivo .env
    """
    email = os.getenv("MW_EMAIL")
    password = os.getenv("MW_PASSWORD")

    if not email or not password:
        logger.error("Faltan credenciales en .env")
        return False

    if "tu_email" in email:
        logger.error("Cambiá las credenciales en el archivo .env antes de correr el bot")
        return False

    logger.info(f"Intentando login con {email}...")

    try:
        await page.goto("https://microworkers.com/login.php", wait_until="networkidle")
        await asyncio.sleep(random.uniform(1.5, 3.0))

        await page.wait_for_selector("input#Email", timeout=15000)

        await page.click("input#Email")
        await asyncio.sleep(random.uniform(0.3, 0.8))
        await page.type("input#Email", email, delay=random.randint(60, 120))

        await asyncio.sleep(random.uniform(0.5, 1.2))

        await page.click("input#Password")
        await asyncio.sleep(random.uniform(0.3, 0.8))
        await page.type("input#Password", password, delay=random.randint(50, 100))

        await asyncio.sleep(random.uniform(0.8, 1.5))

        await page.click("input[name='Button'][type='submit']")
        await page.wait_for_load_state("networkidle", timeout=20000)
        await asyncio.sleep(2)

        if "login.php" in page.url:
            logger.error("Login fallido. Verificá email y password en .env")
            await page.screenshot(path="screenshots/error_login.png")
            return False

        logger.success(f"Login exitoso. URL actual: {page.url}")
        return True

    except Exception as e:
        logger.error(f"Error durante el login: {e}")
        await page.screenshot(path="screenshots/error_login.png")
        return False


async def verificar_sesion_activa(page: Page) -> bool:
    """
    Verifica si hay sesión activa navegando a jobs.php.
    Si redirige a login.php, la sesión expiró.
    """
    try:
        await page.goto("https://www.microworkers.com/jobs.php", wait_until="networkidle")
        await asyncio.sleep(1)

        if "login.php" in page.url:
            logger.warning("Sesión expirada, necesita re-login")
            return False

        logger.info("Sesión activa verificada")
        return True

    except Exception as e:
        logger.error(f"Error verificando sesión: {e}")
        return False
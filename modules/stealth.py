import asyncio
import random
from playwright.async_api import Browser, BrowserContext, Page

USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
]

async def crear_contexto_stealth(browser: Browser) -> BrowserContext:
    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        timezone_id="America/New_York",
        color_scheme="light",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return context

async def aplicar_stealth(page: Page):
    """Elimina huellas de automatización sin librerías externas"""
    await page.add_init_script("""
        // Eliminar webdriver
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

        // Simular plugins reales
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });

        // Simular idiomas reales
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

        // Eliminar rastro de Chrome automatizado
        window.chrome = { runtime: {} };

        // Ocultar que es headless
        Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 4 });
        Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

        // Permisos normales
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
        );
    """)

async def scroll_humano(page: Page):
    """Scrollea simulando comportamiento humano"""
    pasos = random.randint(3, 8)
    for _ in range(pasos):
        distancia = random.randint(100, 450)
        await page.evaluate(f"window.scrollBy(0, {distancia})")
        await asyncio.sleep(random.uniform(0.4, 2.0))

    # A veces scrollear hacia arriba
    if random.random() < 0.3:
        await page.evaluate(f"window.scrollBy(0, -{random.randint(50, 200)})")
        await asyncio.sleep(random.uniform(0.5, 1.5))

async def mover_mouse_humano(page: Page):
    """Mueve el mouse a posiciones aleatorias"""
    for _ in range(random.randint(2, 5)):
        x = random.randint(100, 1200)
        y = random.randint(100, 600)
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.2, 0.8))
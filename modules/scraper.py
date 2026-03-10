import asyncio
import re
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List
from loguru import logger
from playwright.async_api import Page
from .database import tarea_ya_procesada, guardar_tarea

Path("screenshots").mkdir(exist_ok=True)

# ─────────────────────────────────────────────
# Tipos que SÍ podemos automatizar
# ─────────────────────────────────────────────
TIPOS_AUTOMATIZABLES = [
    "automatic verification",           # wizardly1.com — solo visita + código auto
    "search + visit (automatic",        # idem, con paréntesis
]

# Tipos TTV que aceptamos intentar
TIPOS_TTV_AUTOMATIZABLES = [
    "search + visit",
    "search+visit",
    "buscar + visitar",
]

# Excluir siempre si el título contiene esto
EXCLUIR_SI_CONTIENE = [
    "sign up", "signup", "register", "create an account", "crear cuenta",
    "gmail", "youtube", "download", "install", "screenshot",
    "comment", "post", "follow", "subscribe", "like", "rate",
    "forum", "reddit", "twitter", "tiktok", "instagram",
    "qualification", "test", "survey", "webcam", "photo", "video",
    "share", "obtain info", "provide info", "answer", "answer question",
    "fill", "form", "quiz",
]



# TTV de baja señal/alta tasa de lock para este bot
EXCLUIR_TTV_TITULO = [
    "int page",
    "+ bonus",
]

@dataclass
class Tarea:
    id: str
    titulo: str
    pago: float
    url: str
    automatizable: bool = False
    es_ttv: bool = False


def es_automatizable(titulo: str) -> bool:
    texto = titulo.lower()

    # Excluir siempre primero
    if any(e in texto for e in EXCLUIR_SI_CONTIENE):
        return False

    # Aceptar Automatic Verification (normal, muy confiable)
    if any(t in texto for t in TIPOS_AUTOMATIZABLES):
        return True

    # Aceptar TTV de tipo search+visit/engage (sin obtain info, sin screenshot)
    if re.match(r"^\s*ttv\b", texto):
        if any(e in texto for e in EXCLUIR_TTV_TITULO):
            return False
        if any(t in texto for t in TIPOS_TTV_AUTOMATIZABLES):
            return True

    return False


async def _extraer_tareas_pagina(page: Page) -> list:
    return await page.evaluate("""
        () => {
            const tareas = [];
            document.querySelectorAll("div.jobslist, .jobslist, [id^='campaign']").forEach((el) => {
                const idAttr = el.id || '';
                const id = idAttr.replace('campaign', '');
                const link = el.querySelector('.jobname a');
                const titulo = link?.textContent?.trim() || '';
                const url = link?.href || '';
                const pagoTexto = el.querySelector('.jobpayment p')?.textContent?.trim() || '0';
                const pago = parseFloat(pagoTexto.replace('$', '')) || 0;
                if (titulo && url && id) {
                    tareas.push({ id, titulo, pago, url });
                }
            });
            return tareas;
        }
    """)


async def obtener_tareas(page: Page, min_pago: float = 0.04, max_paginas: int = 5) -> List[Tarea]:
    tareas = []
    ids_vistos = set()

    try:
        for pagina in range(1, max_paginas + 1):
            url = f"https://www.microworkers.com/jobs.php?Sort=NEWEST&page={pagina}"
            logger.info(f"Scrapeando página {pagina}/{max_paginas}...")
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(random.uniform(2, 3))

            lista_selector = "div.jobslist, .jobslist, [id^='campaign']"
            try:
                await page.wait_for_selector(lista_selector, timeout=10000)
            except Exception:
                logger.warning(f"No se detectó listado de tareas en página {pagina}, continuando")
                continue

            items_raw = await _extraer_tareas_pagina(page)
            logger.info(f"  Página {pagina}: {len(items_raw)} tareas encontradas")

            nuevas_en_pagina = 0
            for item in items_raw:
                if item['id'] in ids_vistos:
                    continue
                ids_vistos.add(item['id'])
                if item['pago'] < min_pago:
                    continue
                if tarea_ya_procesada(item['id']):
                    logger.debug(f"Tarea {item['id']} ya procesada, saltando")
                    continue

                automatizable = es_automatizable(item['titulo'])
                es_ttv = "ttv.microworkers.com" in item['url']

                tarea = Tarea(
                    id=item['id'],
                    titulo=item['titulo'],
                    pago=item['pago'],
                    url=item['url'],
                    automatizable=automatizable,
                    es_ttv=es_ttv,
                )
                guardar_tarea(
                    tarea.id, tarea.titulo, tarea.pago,
                    "auto" if automatizable else "manual",
                    tarea.url, "pendiente"
                )
                if automatizable:
                    tareas.append(tarea)
                    nuevas_en_pagina += 1

            logger.info(f"  Página {pagina}: {nuevas_en_pagina} automatizables nuevas")
            if len(tareas) >= 20:
                logger.info("Suficientes tareas encontradas, deteniendo paginación")
                break
            await asyncio.sleep(random.uniform(1, 2))

        # Ordenar: Automatic Verification primero (más confiables), luego por pago
        tareas.sort(key=lambda t: (
            2 if "automatic verification" in t.titulo.lower() else 1,
            t.pago
        ), reverse=True)

        logger.info(f"Tareas automatizables encontradas: {len(tareas)}")
        for t in tareas[:15]:
            logger.info(f"  → ${t.pago:.2f} | {t.titulo[:60]}")
        return tareas

    except Exception as e:
        logger.error(f"Error scrapeando tareas: {e}")
        await page.screenshot(path="screenshots/error_scraper.png")
        return []


async def _obtener_keyword_dinamica(page: Page, url_keyword: str) -> str:
    """
    Visita una URL que contiene la keyword real.
    Extrae la keyword del texto de la página.
    """
    try:
        await page.goto(url_keyword, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(random.uniform(1.5, 2.5))
        texto = await page.evaluate("() => document.body.innerText")
        logger.debug(f"Página keyword dinámica: {texto[:300]}")

        kw = (
            re.search(r'keyword[:\s]+([^\n]{3,100})', texto, re.I) or
            re.search(r'search[:\s]+"([^"]+)"', texto, re.I) or
            re.search(r'busca[r]?[:\s]+([^\n]{3,100})', texto, re.I) or
            re.search(r'phrase[:\s]+([^\n]{3,100})', texto, re.I) or
            re.search(r'query[:\s]+([^\n]{3,100})', texto, re.I)
        )
        if kw:
            keyword = kw.group(1).strip().strip('"\'')
            logger.info(f"Keyword dinámica extraída: '{keyword}'")
            return keyword

        # Heurística: preferir frases cortas sin puntos ni URLs
        lineas = [l.strip() for l in texto.split('\n') if 5 < len(l.strip()) < 80]
        if lineas:
            candidatos = [l for l in lineas if '.' not in l and 'http' not in l]
            if candidatos:
                keyword = min(candidatos, key=len)
                logger.info(f"Keyword dinámica (heurística corta): '{keyword}'")
                return keyword

    except Exception as e:
        logger.error(f"Error obteniendo keyword dinámica de {url_keyword}: {e}")
    return ""


def _normalizar_keyword(keyword: str) -> str:
    texto = (keyword or "").strip().strip("\"'`")
    texto = re.sub(r"\s+", " ", texto)
    texto = re.split(r"\b(note|please|step|it will be|you must|do not)\b", texto, flags=re.I)[0].strip()
    return texto.strip(" .:-")


def _detectar_buscador(texto: str, titulo: str) -> str:
    blob = f"{titulo}\n{texto}".lower()
    if "bing" in blob:
        return "bing"
    if "startpage" in blob:
        return "startpage"
    return "google"


async def _extraer_texto_ttv_enriquecido(page: Page) -> str:
    """Intenta recuperar más texto útil cuando taskv2 aún no renderiza completo."""
    texto = await page.evaluate("() => document.body.innerText")
    if len(texto.strip()) > 450:
        return texto

    # Espera render adicional
    await asyncio.sleep(5)
    texto2 = await page.evaluate("() => document.body.innerText")
    if len(texto2.strip()) > len(texto.strip()):
        texto = texto2

    # Extrae secciones que a veces quedan fuera del body principal
    extra = await page.evaluate("""
        () => {
            const sels = ['.task-description', '.instructions', '.task-card', '.content', '#app'];
            const parts = [];
            for (const sel of sels) {
                for (const el of document.querySelectorAll(sel)) {
                    const t = (el.innerText || '').trim();
                    if (t.length > 20) parts.push(t);
                }
            }
            return parts.join('\n');
        }
    """)

    if extra:
        texto = (texto + "\n" + extra).strip()

    return texto


async def obtener_detalle_tarea(page: Page, tarea: Tarea) -> dict:
    """
    Obtiene el detalle completo de una tarea.
    - TTV: navega al preview, acepta, verifica errores en body Y en URL,
      luego extrae instrucciones de taskv2.
    - Normal (Automatic Verification): devuelve flag para que el executor
      construya la URL de wizardly1.com directamente.
    """
    try:
        await page.goto(tarea.url, wait_until="networkidle")
        await asyncio.sleep(random.uniform(1.5, 2.5))

        es_ttv = "ttv.microworkers.com" in page.url

        # ─────────────────────────────────────────
        # FLUJO TTV
        # ─────────────────────────────────────────
        if es_ttv:
            body_text = await page.evaluate("() => document.body.innerText")

            # Tarea no encontrada
            if "Campaign Not found" in body_text:
                logger.warning(f"Tarea {tarea.id} expiró (Campaign Not found)")
                return {"expirada": True, "es_ttv": True}

            # Sin slots ANTES de aceptar
            if "TTVSlot-E0002" in body_text:
                logger.warning(f"Tarea {tarea.id} sin slots disponibles (pre-click)")
                return {"bloqueada": True, "es_ttv": True}

            btn = await page.query_selector("button.btn.btn-primary")
            if not btn:
                logger.warning(f"Sin botón Accept en tarea {tarea.id}")
                return {"expirada": True, "es_ttv": True}

            await btn.click()
            await asyncio.sleep(random.uniform(3, 5))
            url_task = page.url
            logger.info(f"  Post-accept: {url_task}")

            # Redirigió a locked-jobs
            if "locked-jobs" in url_task:
                if "error=" in url_task:
                    logger.warning(f"Tarea {tarea.id} error de plataforma post-accept ({url_task}), no reintentar")
                    return {"expirada": True, "es_ttv": True}
                logger.warning(f"Tarea {tarea.id} ya fue aceptada/bloqueada")
                return {"bloqueada": True, "es_ttv": True}

            # Error en la URL de redirección
            if "ttv.microworkers.com" in url_task and "error=" in url_task:
                error_match = re.search(r'error=([^&]+)', url_task)
                error_msg = error_match.group(1) if error_match else "desconocido"
                logger.warning(f"Tarea {tarea.id} error post-accept en URL: {error_msg}")
                return {"expirada": True, "es_ttv": True}

            # *** FIX CLAVE: verificar body post-click aunque URL no cambie ***
            # Microworkers a veces devuelve el error en el body sin redirigir
            texto_post_click = await page.evaluate("() => document.body.innerText")
            if "TTVSlot-E0002" in texto_post_click:
                logger.warning(f"Tarea {tarea.id} sin slots (E0002 en body post-click)")
                return {"bloqueada": True, "es_ttv": True}
            if "TTVJob-E0002" in texto_post_click or "has expired" in texto_post_click.lower():
                logger.warning(f"Tarea {tarea.id} expirada (error en body post-click)")
                return {"expirada": True, "es_ttv": True}

            # Si no llegó a taskv2, algo salió mal
            if "taskv2.microworkers.com" not in url_task:
                logger.warning(f"Tarea {tarea.id} no redirigió a taskv2 (URL: {url_task})")
                return {"expirada": True, "es_ttv": True}

            # Esperar render React/Vue y enriquecer texto si viene incompleto
            await asyncio.sleep(random.uniform(2, 4))
            texto = await _extraer_texto_ttv_enriquecido(page)

            logger.debug(f"Texto taskv2 ({len(texto)} chars): {texto[:500]}")

            # ── Extraer keyword ─────────────────────────────────────────-
            kw_match = (
                re.search(r'Search(?:ing)?\s+(?:for|keyword)[:\s]*["\']?([^\n"\']{3,120})', texto, re.I) or
                re.search(r'perform\s+a\s+search\s+on\s+(?:google|bing|startpage)[^:\n]*:\s*([^\n]{3,120})', texto, re.I) or
                re.search(r'(?:on\s+)?(?:google|bing|startpage)\s*(?:bar|search)?[^:\n]*:\s*([^\n]{3,120})', texto, re.I) or
                re.search(r'Search Keyword\s*\n+([^\n]{3,120})', texto, re.I) or
                re.search(r'keyword\s*(?:is|:)\s*["\']?([^\n"\']{3,120})', texto, re.I) or
                re.search(r'(?:type|enter|write|use)\s+(?:the\s+)?keyword[:\s]+([^\n]{3,120})', texto, re.I) or
                re.search(r'search\s+(?:for\s+)?["\']([^"\']{3,120})["\']', texto, re.I) or
                re.search(r'Step\s*1[^:]*:\s*(?:Search|Go to)[^:]*["\']([^"\']{3,120})["\']', texto, re.I)
            )
            keyword = _normalizar_keyword(kw_match.group(1)) if kw_match else ""
            search_engine = _detectar_buscador(texto, tarea.titulo)

            # ── Extraer dominio destino ──────────────────────────────────
            dom_match = (
                re.search(r'(?:visit|go to|open|navigate to)\s+(https?://[^\s\n]{5,100})', texto, re.I) or
                re.search(r'Domain[^:]*:\s*(https?://[^\s\n]{5,100})', texto, re.I) or
                re.search(r'website[:\s]+(https?://[^\s\n]{5,100})', texto, re.I) or
                re.search(r'starting with[:\s]+(https?://[^\s\n]{5,100})', texto, re.I)
            )
            dominio = dom_match.group(1).strip() if dom_match else ""

            # ── Extraer links externos ───────────────────────────────────
            links = await page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.href)
                    .filter(h => h.startsWith('http')
                        && !h.includes('microworkers')
                        && !h.includes('youtube')
                        && !h.includes('twitter')
                        && !h.includes('snipboard')
                        && !h.includes('google.com'))
            """)

            # ── Keyword dinámica ─────────────────────────────────────────
            KEYWORD_DINAMICA = ["get your keyword", "get keyword", "obtener keyword",
                                "click here for keyword", "visit for keyword",
                                "click the link", "visit this link"]
            if not keyword or any(k in keyword.lower() for k in KEYWORD_DINAMICA):
                if links:
                    logger.info(f"Keyword dinámica detectada, visitando: {links[0]}")
                    keyword = await _obtener_keyword_dinamica(page, links[0])
                    await page.goto(url_task, wait_until="networkidle")
                    await asyncio.sleep(1)

            # Si no hay señales mínimas, tratar como temporal/no lista
            if not keyword and not dominio and not links:
                logger.warning(f"Tarea {tarea.id} sin datos útiles (render incompleto o tarea opaca), aplazando")
                return {"bloqueada": True, "es_ttv": True, "sin_datos": True}

            # ── Flags de proof requerido ─────────────────────────────────
            pide_screenshot = bool(re.search(r'screenshot', texto, re.I))
            pide_social     = bool(re.search(r'social media', texto, re.I))
            pide_url        = bool(re.search(r'landing page url|paste.*url', texto, re.I))
            pide_code       = bool(re.search(r'\bcode\b|código', texto, re.I))

            logger.info(f"  keyword='{keyword}' dominio='{dominio}' buscador='{search_engine}'")
            logger.info(f"  screenshot={pide_screenshot} social={pide_social} url={pide_url} code={pide_code} links={links[:3]}")

            return {
                "es_ttv": True,
                "url_task": url_task,
                "texto_completo": texto[:2000],
                "keyword": keyword,
                "dominio_destino": dominio,
                "url_destino": links[0] if links else dominio,
                "todos_los_links": links,
                "pide_screenshot": pide_screenshot,
                "pide_social_media": pide_social,
                "pide_url": pide_url,
                "pide_code": pide_code,
                "tiempo_requerido": "30",
                "search_engine": search_engine,
            }

        # ─────────────────────────────────────────
        # FLUJO NORMAL (Automatic Verification)
        # ─────────────────────────────────────────
        else:
            body_text = await page.evaluate("() => document.body.innerText")

            if "Job not found" in body_text:
                logger.warning(f"Tarea {tarea.id} no existe (Job not found)")
                return {"expirada": True, "es_ttv": False}

            # Para Automatic Verification: extraer URL real de verificación si existe
            if "automatic verification" in tarea.titulo.lower():
                links_externos = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => h.startsWith('http') && !h.includes('microworkers'))
                """)
                url_verif = next((u for u in links_externos if 'mw_camp=' in u), "")
                logger.info(
                    f"  Automatic Verification: links={len(links_externos)} "
                    f"url_verif={'sí' if url_verif else 'no'}"
                )
                return {
                    "es_ttv": False,
                    "es_automatic_verification": True,
                    "instrucciones": body_text[:2000],
                    "url_destino": "",
                    "todos_los_links": links_externos,
                    "url_verificacion": url_verif,
                    "tiempo_requerido": "30",
                    "search_engine": "google",
                }

            # Para otros tipos normales, extraer URL del jobdetailsbox
            detalle = await page.evaluate("""
                () => {
                    const jobbox = document.querySelector('.jobdetailsbox');
                    const links = jobbox
                        ? Array.from(jobbox.querySelectorAll('a[href]'))
                            .map(a => a.href)
                            .filter(h => h.startsWith('http') && !h.includes('microworkers'))
                        : [];
                    const allLinks = Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => h.startsWith('http')
                            && !h.includes('microworkers')
                            && !h.includes('javascript'));
                    const instrucciones = jobbox?.innerText?.trim()
                        || document.body.innerText.substring(0, 2000);
                    const tiempoMatch = instrucciones.match(/(\\d+)\\s*(min|second|seg)/i);
                    return {
                        es_ttv: false,
                        instrucciones: instrucciones,
                        url_destino: links[0] || allLinks[0] || '',
                        todos_los_links: links.length ? links : allLinks.slice(0, 5),
                        tiempo_requerido: tiempoMatch ? tiempoMatch[1] : '30',
                    }
                }
            """)

            detalle['search_engine'] = _detectar_buscador(detalle.get('instrucciones', ''), tarea.titulo)
            logger.info(f"  Normal: {len(detalle.get('todos_los_links',[]))} links, url='{detalle.get('url_destino','')}' buscador='{detalle['search_engine']}'")
            return detalle

    except Exception as e:
        logger.error(f"Error obteniendo detalle {tarea.id}: {e}")
        return {}

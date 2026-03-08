import asyncio
import re
import random
from dataclasses import dataclass
from typing import List
from loguru import logger
from playwright.async_api import Page
from .database import tarea_ya_procesada, guardar_tarea

TIPOS_AUTOMATIZABLES = [
    "visit", "search + visit", "buscar + visitar", "obtain info",
    "automatic verification",
    "bing", "startpage", "ggl", "google",
    "buscar + clic", "buscar y dar clic",
    "palabra clave", "keyword",
    "search + engage", "search+visit", "clic + código", "click + code",
]

EXCLUIR_SI_CONTIENE = [
    "sign up", "signup", "register", "create an account", "crear cuenta",
    "gmail", "youtube: create", "download", "install", "screenshot",
    "comment", "post", "follow", "subscribe", "like", "rate",
    "forum", "reddit", "twitter", "tiktok", "instagram",
    "qualification", "test", "survey", "webcam", "photo", "video",
    "share",
]

@dataclass
class Tarea:
    id: str
    titulo: str
    pago: float
    url: str
    automatizable: bool = False

def es_automatizable(titulo: str) -> bool:
    texto = titulo.lower()
    if any(e in texto for e in EXCLUIR_SI_CONTIENE):
        return False
    return any(t in texto for t in TIPOS_AUTOMATIZABLES)

async def _extraer_tareas_pagina(page: Page) -> list:
    return await page.evaluate("""
        () => {
            const tareas = [];
            document.querySelectorAll('div.jobslist').forEach((el) => {
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

            try:
                await page.wait_for_selector("div.jobslist", timeout=10000)
            except:
                logger.warning(f"No hay tareas en página {pagina}, deteniendo")
                break

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
                tarea = Tarea(id=item['id'], titulo=item['titulo'],
                              pago=item['pago'], url=item['url'],
                              automatizable=automatizable)
                guardar_tarea(tarea.id, tarea.titulo, tarea.pago,
                              "auto" if automatizable else "manual",
                              tarea.url, "pendiente")
                if automatizable:
                    tareas.append(tarea)
                    nuevas_en_pagina += 1

            logger.info(f"  Página {pagina}: {nuevas_en_pagina} automatizables nuevas")
            if len(tareas) >= 20:
                logger.info("Suficientes tareas encontradas, deteniendo paginación")
                break
            await asyncio.sleep(random.uniform(1, 2))

        tareas.sort(key=lambda t: (
            2 if "automatic verification" in t.titulo.lower() else
            1 if "search + visit" in t.titulo.lower() or "buscar + visitar" in t.titulo.lower() else 0,
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
    Visita una URL que contiene la keyword real (ej: the-cosmicglobe.com/hydrox5.html).
    Extrae la keyword del texto de la página.
    """
    try:
        await page.goto(url_keyword, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(random.uniform(1.5, 2.5))
        texto = await page.evaluate("() => document.body.innerText")
        logger.debug(f"Página keyword dinámica: {texto[:300]}")

        # Buscar keyword en distintos formatos
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

        # Si no hay patrón claro, tomar la línea más larga no vacía (probable keyword)
        lineas = [l.strip() for l in texto.split('\n') if len(l.strip()) > 5]
        if lineas:
            keyword = max(lineas, key=len)[:100]
            logger.info(f"Keyword dinámica (heurística): '{keyword}'")
            return keyword

    except Exception as e:
        logger.error(f"Error obteniendo keyword dinámica de {url_keyword}: {e}")
    return ""


async def obtener_detalle_tarea(page: Page, tarea: Tarea) -> dict:
    """
    - TTV: navega al preview, acepta, extrae instrucciones reales de taskv2.
      Si la keyword es dinámica, visita el link para obtenerla.
    - Normal: extrae de .jobdetailsbox.
    - "Palabra Clave": extrae keyword del texto de la página.
    """
    try:
        await page.goto(tarea.url, wait_until="networkidle")
        await asyncio.sleep(random.uniform(1.5, 2.5))

        es_ttv = "ttv.microworkers.com" in page.url

        if es_ttv:
            body_text = await page.evaluate("() => document.body.innerText")
            if "Campaign Not found" in body_text:
                logger.warning(f"Tarea {tarea.id} expiró")
                return {"expirada": True, "es_ttv": True}

            btn = await page.query_selector("button.btn.btn-primary")
            if not btn:
                logger.warning(f"Sin botón Accept en tarea {tarea.id}")
                return {"es_ttv": True}

            await btn.click()
            await asyncio.sleep(random.uniform(3, 5))
            url_task = page.url
            logger.info(f"  Post-accept: {url_task}")

            # Si redirigió a locked-jobs, ya fue aceptada antes
            if "locked-jobs" in url_task:
                logger.warning(f"Tarea {tarea.id} ya fue aceptada/bloqueada")
                return {"bloqueada": True, "es_ttv": True}

            texto = await page.evaluate("() => document.body.innerText")

            # Extraer keyword
            kw = (
                re.search(r'Copy and paste[^:]*:\s*\n*([^\n]+)', texto, re.I) or
                re.search(r'Search Keyword\s*\n+([^\n]+)', texto, re.I) or
                re.search(r'keyword[:\s]+([^\n]{3,80})', texto, re.I)
            )
            keyword = kw.group(1).strip() if kw else ""

            # Dominio destino
            dom = (
                re.search(r'Domain[^:]*:\s*(https?://[^\s]+)', texto, re.I) or
                re.search(r'starting with[:\s]+(https?://[^\s]+)', texto, re.I)
            )
            dominio = dom.group(1).strip() if dom else ""

            # Links externos (excluir utilidades)
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

            # Keyword dinámica: si dice "GET YOUR KEYWORD" visitar el link
            KEYWORD_DINAMICA = ["get your keyword", "get keyword", "obtener keyword",
                                "click here for keyword", "visit for keyword"]
            if not keyword or any(k in keyword.lower() for k in KEYWORD_DINAMICA):
                if links:
                    logger.info(f"Keyword dinámica detectada, visitando: {links[0]}")
                    keyword = await _obtener_keyword_dinamica(page, links[0])
                    # Volver a la página de la tarea
                    await page.goto(url_task, wait_until="networkidle")
                    await asyncio.sleep(1)

            pide_screenshot = bool(re.search(r'screenshot', texto, re.I))
            pide_social     = bool(re.search(r'social media', texto, re.I))
            pide_url        = bool(re.search(r'landing page url|paste.*url', texto, re.I))
            pide_code       = bool(re.search(r'\bcode\b|código', texto, re.I))

            logger.info(f"  keyword='{keyword}' dominio='{dominio}'")
            logger.info(f"  screenshot={pide_screenshot} social={pide_social} url={pide_url} code={pide_code} links={links}")

            return {
                "es_ttv": True,
                "url_task": url_task,
                "texto_completo": texto[:2000],
                "keyword": keyword,
                "dominio_destino": dominio,
                "url_destino": links[0] if links else "",
                "todos_los_links": links,
                "pide_screenshot": pide_screenshot,
                "pide_social_media": pide_social,
                "pide_url": pide_url,
                "pide_code": pide_code,
                "tiempo_requerido": "30",
            }

        else:
            # Tarea normal jobs_details.php
            body_text = await page.evaluate("() => document.body.innerText")

            if "Job not found" in body_text:
                logger.warning(f"Tarea {tarea.id} no existe (Job not found)")
                return {"expirada": True, "es_ttv": False}

            detalle = await page.evaluate("""
                () => {
                    const jobbox = document.querySelector('.jobdetailsbox');
                    const links = jobbox
                        ? Array.from(jobbox.querySelectorAll('a[href]'))
                            .map(a => a.href)
                            .filter(h => h.startsWith('http') && !h.includes('microworkers'))
                        : [];
                    const instrucciones = jobbox?.innerText?.trim()
                        || document.body.innerText.substring(0, 2000);
                    const tiempoMatch = instrucciones.match(/(\d+)\s*(min|second|seg)/i);
                    return {
                        es_ttv: false,
                        instrucciones: instrucciones,
                        url_destino: links[0] || '',
                        todos_los_links: links,
                        tiempo_requerido: tiempoMatch ? tiempoMatch[1] : '30',
                    }
                }
            """)

            # Para "Palabra Clave": extraer keyword e URL del texto de instrucciones
            titulo_lower = tarea.titulo.lower()
            if "palabra clave" in titulo_lower or "buscar + clic" in titulo_lower:
                instrucciones = detalle.get("instrucciones", "")
                kw = (
                    re.search(r'palabra clave[:\s]+([^\n]{3,100})', instrucciones, re.I) or
                    re.search(r'keyword[:\s]+([^\n]{3,100})', instrucciones, re.I) or
                    re.search(r'busca[r]?[:\s]+"([^"]+)"', instrucciones, re.I) or
                    re.search(r'"([^"]{5,80})"', instrucciones)
                )
                url_m = re.search(r'https?://[^\s<>"]+', instrucciones)

                if kw:
                    detalle["keyword"] = kw.group(1).strip().strip('"\'')
                if url_m and not detalle.get("url_destino"):
                    detalle["url_destino"] = url_m.group(0)
                detalle["es_palabra_clave"] = True
                logger.info(f"  Palabra Clave: keyword='{detalle.get('keyword','')}' url='{detalle.get('url_destino','')}'")

            logger.info(f"  Normal: {len(detalle.get('todos_los_links',[]))} links, url='{detalle.get('url_destino','')}'")
            return detalle

    except Exception as e:
        logger.error(f"Error obteniendo detalle {tarea.id}: {e}")
        return {}

import asyncio
import re
import random
import os
from pathlib import Path
from loguru import logger
from playwright.async_api import Page
from .scraper import Tarea, obtener_detalle_tarea
from .stealth import scroll_humano, mover_mouse_humano
from .database import marcar_completada, marcar_bloqueada, guardar_tarea

Path("screenshots").mkdir(exist_ok=True)


def _url_buscador(search_engine: str, keyword: str) -> str:
    q = keyword.replace(" ", "+")
    engine = (search_engine or "google").lower()
    if engine == "bing":
        return f"https://www.bing.com/search?q={q}"
    if engine == "startpage":
        return f"https://www.startpage.com/sp/search?query={q}"
    return f"https://www.google.com/search?q={q}"




def _normalizar_dominio_objetivo(dominio: str) -> str:
    d = (dominio or "").lower().strip()
    d = d.replace("https://", "").replace("http://", "").split("/")[0]
    d = d.replace("www.", "")
    d = d.replace("*", "")
    return d


async def _enviar_proof_ttv(page: Page, url_task: str, proof: str) -> bool:
    if not url_task:
        return False

    await page.goto(url_task, wait_until="networkidle")
    await asyncio.sleep(2)

    campos = await page.query_selector_all("input[type='text'], input[type='url'], textarea")
    if not campos:
        logger.warning("No se encontraron campos de proof en la tarea TTV")
        return False

    llenado = False
    for campo in campos:
        ph = ((await campo.get_attribute("placeholder")) or "").lower()
        fid = ((await campo.get_attribute("id")) or "").lower()
        name = ((await campo.get_attribute("name")) or "").lower()
        if any(w in (ph + fid + name) for w in ["url", "landing", "paste", "proof", "answer", "code"]):
            await campo.fill(proof)
            llenado = True
            break

    if not llenado:
        await campos[0].fill(proof)

    for sel in ["button:has-text('Finish')", "button:has-text('Submit')", "input[type='submit']", ".btn-success", ".btn-primary"]:
        btn = await page.query_selector(sel)
        if not btn:
            continue

        txt = (await btn.inner_text() or "").lower().strip()
        val = ((await btn.get_attribute("value")) or "").lower().strip()
        if any(w in (txt + " " + val) for w in ["finish", "submit", "send", "enviar", "done", "complete"]):
            await btn.click()
            await asyncio.sleep(3)
            return True

    return False

async def ejecutar_tarea(page: Page, tarea: Tarea) -> bool:
    logger.info(f"Ejecutando tarea: {tarea.titulo[:60]} | Pago: ${tarea.pago:.2f}")

    exito = False
    bloqueada = False
    try:
        titulo = tarea.titulo.lower()

        if "automatic verification" in titulo:
            exito = await _tarea_search_visit_auto(page, tarea)

        elif any(t in titulo for t in ["create an account", "crear cuenta",
                                        "gmail", "sign up", "signup", "register"]):
            logger.warning(f"Requiere cuenta real, saltando: {tarea.titulo[:50]}")
            exito = False

        elif any(t in titulo for t in ["visit", "website", "buscar + visitar",
                                        "search + visit", "obtain info", "obtain code",
                                        "bing", "google", "startpage",
                                        "buscar + clic", "keyword", "palabra clave",
                                        "search + engage", "engage"]):
            exito, bloqueada = await _tarea_visitar_url(page, tarea)

        elif any(t in titulo for t in ["youtube", "watch", "search + watch"]):
            exito = await _tarea_youtube(page, tarea)

        else:
            logger.warning(f"Tipo no implementado: {tarea.titulo[:50]}")
            exito = False

    except Exception as e:
        logger.error(f"Error inesperado en tarea {tarea.id}: {e}")
        exito = False

    if exito:
        marcar_completada(tarea.id)
        logger.success(f"✓ Tarea completada: {tarea.titulo[:50]}")
    elif bloqueada:
        marcar_bloqueada(tarea.id)
        logger.info(f"⏸ Tarea bloqueada (sin slots): {tarea.titulo[:50]}")
    else:
        guardar_tarea(tarea.id, tarea.titulo, tarea.pago, "manual", tarea.url, "fallida")
        logger.warning(f"✗ Tarea fallida: {tarea.titulo[:50]}")

    return exito


async def _tarea_visitar_url(page: Page, tarea: Tarea):
    """
    Maneja tareas TTV y normales de tipo visit/search.
    Retorna (exito: bool, bloqueada: bool)
    """
    try:
        detalle = await obtener_detalle_tarea(page, tarea)

        if detalle.get("expirada"):
            logger.warning(f"Tarea {tarea.id} expirada, saltando")
            return False, False

        if detalle.get("bloqueada"):
            logger.warning(f"Tarea {tarea.id} sin slots/locked, se reintentará")
            return False, True

        es_ttv = detalle.get("es_ttv", False)

        if es_ttv:
            if detalle.get("pide_screenshot") or detalle.get("pide_social_media"):
                logger.warning(f"TTV requiere screenshot/social, saltando: {tarea.titulo[:50]}")
                skip = await page.query_selector("a:has-text('Skip'), button:has-text('Skip')")
                if skip:
                    await skip.click()
                return False, False

            keyword   = detalle.get("keyword", "")
            dominio   = detalle.get("dominio_destino", "")
            url_task  = detalle.get("url_task", "")
            pide_code = detalle.get("pide_code", False)
            search_engine = detalle.get("search_engine", "google")

            if not keyword:
                if dominio or detalle.get("url_destino", ""):
                    logger.warning(f"Sin keyword en TTV {tarea.id}; usando fallback directo por dominio/url")
                    keyword = ""
                elif detalle.get("sin_datos"):
                    logger.warning(f"Sin datos de instrucciones en TTV {tarea.id}; reintento diferido")
                    return False, True
                else:
                    logger.warning(f"Sin keyword en tarea TTV {tarea.id}")
                    return False, False

            logger.info(f"TTV Search: keyword='{keyword}' dominio='{dominio}' buscador='{search_engine}'")

            url_visitada = ""
            if keyword:
                await page.goto(
                    _url_buscador(search_engine, keyword),
                    wait_until="networkidle"
                )
                await asyncio.sleep(random.uniform(2, 4))
                await scroll_humano(page)

            if dominio:
                dominio_limpio = _normalizar_dominio_objetivo(dominio)
                links_res = await page.evaluate(f"""
                    () => Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => h.startsWith('http') && h.toLowerCase().includes('{dominio_limpio}'))
                """)
                if not links_res and keyword:
                    if (search_engine or "google").lower() == "bing":
                        await page.goto(
                            f"https://www.bing.com/search?q={keyword.replace(' ','+')}&first=11",
                            wait_until="networkidle"
                        )
                    else:
                        await page.goto(
                            f"https://www.google.com/search?q={keyword.replace(' ','+')}&start=10",
                            wait_until="networkidle"
                        )
                    await asyncio.sleep(2)
                    links_res = await page.evaluate(f"""
                        () => Array.from(document.querySelectorAll('a[href]'))
                            .map(a => a.href)
                            .filter(h => h.startsWith('http') && h.toLowerCase().includes('{dominio_limpio}'))
                    """)
                if links_res:
                    url_visitada = links_res[0]
                    logger.info(f"Resultado: {url_visitada}")
                    await page.goto(url_visitada, wait_until="networkidle", timeout=30000)
                elif not keyword:
                    url_visitada = dominio if dominio.startswith("http") else f"https://{dominio_limpio}"
                    logger.info(f"Sin keyword; visitando dominio directo: {url_visitada}")
                    await page.goto(url_visitada, wait_until="networkidle", timeout=30000)
                else:
                    logger.warning(f"No se encontró dominio {dominio_limpio} en resultados de {search_engine}")
                    return False, False
            else:
                try:
                    await page.locator("div#search a[href^='http']").first.click()
                    await asyncio.sleep(3)
                    url_visitada = page.url
                except:
                    logger.warning("No se pudo hacer click en resultado")
                    return False, False

            await asyncio.sleep(random.uniform(20, 35))
            for _ in range(random.randint(3, 5)):
                await page.evaluate(f"window.scrollBy(0, {random.randint(200, 500)})")
                await asyncio.sleep(random.uniform(1, 3))

            codigo = ""
            if pide_code:
                texto_pag = await page.evaluate("() => document.body.innerText")
                cod = (
                    re.search(r'verification\s*code[:\s]+([A-Z0-9]{4,20})', texto_pag, re.I) or
                    re.search(r'\bcode[:\s]+([A-Z0-9]{4,20})\b', texto_pag, re.I)
                )
                if cod:
                    codigo = cod.group(1).strip()
                    logger.info(f"Código: {codigo}")

            if url_task:
                proof = codigo if codigo else url_visitada
                enviado = await _enviar_proof_ttv(page, url_task, proof)
                if enviado:
                    logger.success(f"✓ TTV submitada: {tarea.titulo[:50]}")
                    return True, False

            return False, False

        else:
            if detalle.get("expirada"):
                return False, False

            es_palabra_clave = detalle.get("es_palabra_clave", False)
            keyword     = detalle.get("keyword", "")
            url_destino = detalle.get("url_destino", "")
            instrucciones = detalle.get("instrucciones", "")
            search_engine = detalle.get("search_engine", "google")

            if es_palabra_clave and keyword:
                logger.info(f"Palabra Clave: keyword='{keyword}' url='{url_destino}' buscador='{search_engine}'")

                await page.goto(
                    _url_buscador(search_engine, keyword),
                    wait_until="networkidle"
                )
                await asyncio.sleep(random.uniform(2, 4))
                await scroll_humano(page)

                url_visitada = ""
                if url_destino:
                    dominio_limpio = url_destino.replace("https://","").replace("http://","").split("/")[0]
                    links_res = await page.evaluate(f"""
                        () => Array.from(document.querySelectorAll('a[href]'))
                            .map(a => a.href)
                            .filter(h => h.includes('{dominio_limpio}') && h.startsWith('http'))
                    """)
                    if links_res:
                        url_visitada = links_res[0]
                        await page.goto(url_visitada, wait_until="networkidle", timeout=30000)
                    else:
                        try:
                            await page.locator("div#search a[href^='http']").first.click()
                            await asyncio.sleep(3)
                            url_visitada = page.url
                        except:
                            return False, False
                else:
                    try:
                        await page.locator("div#search a[href^='http']").first.click()
                        await asyncio.sleep(3)
                        url_visitada = page.url
                    except:
                        return False, False

                await asyncio.sleep(random.uniform(20, 40))
                for _ in range(random.randint(3, 5)):
                    await page.evaluate(f"window.scrollBy(0, {random.randint(200, 500)})")
                    await asyncio.sleep(random.uniform(1, 3))

                texto_pag = await page.evaluate("() => document.body.innerText")
                cod = (
                    re.search(r'c[oó]digo[:\s]+([A-Z0-9]{3,20})', texto_pag, re.I) or
                    re.search(r'code[:\s]+([A-Z0-9]{3,20})', texto_pag, re.I) or
                    re.search(r'\b([A-Z0-9]{5,12})\b', texto_pag)
                )
                codigo = cod.group(1).strip() if cod else url_visitada
                logger.info(f"Proof: {codigo}")

                job_url = f"https://www.microworkers.com/jobs_details.php?Id={tarea.url.split('Id=')[-1]}"
                await page.goto(job_url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(random.uniform(2, 3))
                try:
                    await page.evaluate("show5()")
                    await asyncio.sleep(1)
                except:
                    pass
                await page.fill("textarea#Required_proof", codigo)
                await asyncio.sleep(1)
                await page.click("input[name='B1']")
                await asyncio.sleep(2)
                logger.success(f"✓ Palabra Clave submitada")
                return True, False

            elif url_destino:
                tiempo = max(15, min(int(''.join(filter(str.isdigit,
                             detalle.get("tiempo_requerido","30"))) or 30), 120))
                logger.info(f"Visitando: {url_destino} por {tiempo}s")

                await page.goto(url_destino, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(random.uniform(2, 4))
                await mover_mouse_humano(page)
                await scroll_humano(page)

                transcurrido = 0
                while transcurrido < tiempo:
                    espera = random.uniform(8, 15)
                    await asyncio.sleep(espera)
                    transcurrido += espera
                    if random.random() < 0.4:
                        await scroll_humano(page)

                await page.screenshot(path=f"screenshots/tarea_{tarea.id}_completada.png")

                job_url = f"https://www.microworkers.com/jobs_details.php?Id={tarea.url.split('Id=')[-1]}"
                await page.goto(job_url, wait_until="networkidle", timeout=30000)
                await asyncio.sleep(random.uniform(2, 3))
                try:
                    await page.evaluate("show5()")
                    await asyncio.sleep(1)
                except:
                    pass
                proof = f"Visited: {url_destino}\nTask completed as required.\n{instrucciones[:200]}"
                await page.fill("textarea#Required_proof", proof)
                await asyncio.sleep(1)
                await page.click("input[name='B1']")
                await asyncio.sleep(2)
                logger.success(f"✓ Visita normal submitada")
                return True, False

            else:
                logger.warning(f"Sin URL destino en tarea normal {tarea.id}")
                return False, False

    except Exception as e:
        logger.error(f"Error en _tarea_visitar_url: {e}")
        return False, False


async def _tarea_search_visit_auto(page: Page, tarea: Tarea) -> bool:
    try:
        detalle = await obtener_detalle_tarea(page, tarea)

        if detalle.get("expirada"):
            return False

        instrucciones = detalle.get("instrucciones", "")

        url_match = re.search(r'https?://\S+mw_camp=\S+', instrucciones)
        if not url_match:
            wid = os.getenv("MW_WORKER_ID", "eb815323")
            url_verificacion = f"https://wizardly1.com/mw.php?mw_camp={tarea.id}&mw_wid={wid}"
        else:
            url_verificacion = url_match.group(0).strip()

        logger.info(f"URL verificación: {url_verificacion}")
        await page.goto(url_verificacion, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(random.uniform(2, 3))

        texto = await page.inner_text("body")
        logger.debug(f"Texto wizardly: {texto[:200]}")

        if "Not Found" in texto or "404" in texto:
            logger.warning(f"wizardly1.com devuelve 404 para tarea {tarea.id}, expirada")
            return False

        kw = (
            re.search(r'keyword[:\s]+([^\n<]{3,100})', texto, re.I) or
            re.search(r'search[:\s]+"([^"]+)"', texto, re.I) or
            re.search(r'busca[r]?[:\s]+([^\n<]{3,100})', texto, re.I)
        )

        if not kw or len(kw.group(1).strip()) <= 2:
            logger.warning(f"Keyword inválida en {tarea.id}")
            return False

        keyword = kw.group(1).strip()
        url_destino = detalle.get("url_destino", "")
        search_engine = detalle.get("search_engine", "google")
        logger.info(f"Keyword: '{keyword}' buscador='{search_engine}'")

        await page.goto(_url_buscador(search_engine, keyword),
                        wait_until="networkidle", timeout=30000)
        await asyncio.sleep(random.uniform(2, 4))
        await scroll_humano(page)

        if url_destino:
            dominio = re.search(r'https?://([^/]+)', url_destino)
            if dominio:
                try:
                    await page.locator(f"a[href*='{dominio.group(1)}']").first.click()
                    await asyncio.sleep(3)
                except:
                    await page.goto(url_destino, wait_until="networkidle", timeout=30000)
        else:
            try:
                await page.locator("div#search a[href^='http']").first.click()
                await asyncio.sleep(3)
            except:
                pass

        await asyncio.sleep(random.uniform(3, 5))
        await scroll_humano(page)

        texto_actual = await page.inner_text("body")
        cod = (
            re.search(r'verification\s*code[:\s]+([A-Z0-9]{4,20})', texto_actual, re.I) or
            re.search(r'\bcode[:\s]+([A-Z0-9]{4,20})\b', texto_actual, re.I) or
            re.search(r'\b([A-Z0-9]{6,12})\b', texto_actual)
        )

        if not cod:
            logger.warning(f"No se encontró código en {tarea.id}")
            await page.screenshot(path=f"screenshots/debug_code_{tarea.id}.png")
            return False

        codigo = cod.group(1).strip()
        logger.info(f"Código: {codigo}")
        await page.screenshot(path=f"screenshots/tarea_{tarea.id}_code.png")

        job_url = f"https://www.microworkers.com/jobs_details.php?Id={tarea.url.split('Id=')[-1]}"
        await page.goto(job_url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(random.uniform(2, 3))
        try:
            await page.evaluate("show5()")
            await asyncio.sleep(1)
        except:
            pass
        await page.fill("textarea#Required_proof", codigo)
        await asyncio.sleep(1)
        await page.click("input[name='B1']")
        await asyncio.sleep(2)
        logger.success(f"✓ Auto Verification: {codigo}")
        return True

    except Exception as e:
        logger.error(f"Error en _tarea_search_visit_auto: {e}")
        return False


async def _tarea_youtube(page: Page, tarea: Tarea) -> bool:
    try:
        detalle = await obtener_detalle_tarea(page, tarea)
        url_video = detalle.get("url_destino", "")
        if not url_video or "youtube" not in url_video:
            return False

        await page.goto(url_video, wait_until="networkidle")
        await asyncio.sleep(2)
        try:
            await page.locator("button.ytp-play-button").first.click()
        except:
            pass

        tiempo = max(30, min(int(''.join(filter(str.isdigit,
                     detalle.get("tiempo_requerido","45"))) or 45), 180))
        logger.info(f"Viendo video {tiempo}s")

        transcurrido = 0
        while transcurrido < tiempo:
            espera = random.uniform(10, 20)
            await asyncio.sleep(espera)
            transcurrido += espera
            if random.random() < 0.3:
                await mover_mouse_humano(page)

        await page.screenshot(path=f"screenshots/tarea_{tarea.id}_youtube.png")
        return True

    except Exception as e:
        logger.error(f"Error en _tarea_youtube: {e}")
        return False
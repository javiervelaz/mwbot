import os
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
from tinydb import TinyDB, Query

Path("data").mkdir(exist_ok=True)

db = TinyDB("data/tasks.json")
tareas_table = db.table("tareas")
sesiones_table = db.table("sesiones")
Tarea = Query()
Sesion = Query()

BLOQUEADA_COOLDOWN_HORAS = int(os.getenv("BLOQUEADA_COOLDOWN_HORAS", "2"))

def init_db():
    logger.info("Base de datos inicializada (tinydb)")

def depurar_db():
    """
    Limpia la DB al arrancar:
    - 'pendiente'  → 'fallida'  (atascadas de sesiones anteriores)
    - 'bloqueada'  → eliminadas  (sin slots es temporal, se reintenta siempre)
    - 'fallida' >6h → eliminadas (expiradas, se reintenta si volvieron)
    - 'completada' → intactas
    """
    # 1. Pendientes atascadas → fallidas
    pendientes = tareas_table.search(Tarea.estado == "pendiente")
    if pendientes:
        tareas_table.update({"estado": "fallida"}, Tarea.estado == "pendiente")
        logger.info(f"DB depurada: {len(pendientes)} tareas pendientes → fallidas")

    # 2. Bloqueadas antiguas → eliminar para reintentar (cooldown)
    hace_cooldown = (datetime.now() - timedelta(hours=BLOQUEADA_COOLDOWN_HORAS)).isoformat()
    bloqueadas_viejas = tareas_table.search(
        (Tarea.estado == "bloqueada") & (Tarea.fecha < hace_cooldown)
    )
    if bloqueadas_viejas:
        ids_bloqueadas = [t.doc_id for t in bloqueadas_viejas]
        tareas_table.remove(doc_ids=ids_bloqueadas)
        logger.info(
            f"DB depurada: {len(bloqueadas_viejas)} tareas bloqueadas antiguas "
            f"(>{BLOQUEADA_COOLDOWN_HORAS}h) eliminadas"
        )

    # 3. Fallidas viejas (> 6 horas) → eliminar para reintentarlas
    hace_6h = (datetime.now() - timedelta(hours=6)).isoformat()
    viejas = tareas_table.search(
        (Tarea.estado == "fallida") & (Tarea.fecha < hace_6h)
    )
    if viejas:
        ids_viejas = [t.doc_id for t in viejas]
        tareas_table.remove(doc_ids=ids_viejas)
        logger.info(f"DB depurada: {len(viejas)} tareas fallidas (>6h) eliminadas")

    total = len(tareas_table.all())
    completadas = len(tareas_table.search(Tarea.estado == "completada"))
    fallidas = len(tareas_table.search(Tarea.estado == "fallida"))
    logger.info(f"DB estado: {total} tareas ({completadas} completadas, {fallidas} fallidas)")

def tarea_ya_procesada(tarea_id: str) -> bool:
    """
    Bloquea siempre: completada, fallida (reciente), pendiente.
    Bloquea temporalmente: bloqueada (cooldown), para no perder sesiones
    reintentando tareas sin slots una y otra vez.
    """
    resultado_fijo = tareas_table.search(
        (Tarea.id == tarea_id) &
        (Tarea.estado.one_of(["completada", "fallida", "pendiente"]))
    )
    if resultado_fijo:
        return True

    hace_cooldown = (datetime.now() - timedelta(hours=BLOQUEADA_COOLDOWN_HORAS)).isoformat()
    bloqueada_reciente = tareas_table.search(
        (Tarea.id == tarea_id) &
        (Tarea.estado == "bloqueada") &
        (Tarea.fecha >= hace_cooldown)
    )
    return len(bloqueada_reciente) > 0

def guardar_tarea(tarea_id, titulo, pago, tipo, url, estado="pendiente"):
    existente = tareas_table.search(Tarea.id == tarea_id)
    if existente:
        tareas_table.update({"estado": estado}, Tarea.id == tarea_id)
    else:
        tareas_table.insert({
            "id": tarea_id,
            "titulo": titulo,
            "pago": pago,
            "tipo": tipo,
            "url": url,
            "estado": estado,
            "fecha": datetime.now().isoformat()
        })

def marcar_completada(tarea_id: str):
    tareas_table.update({"estado": "completada"}, Tarea.id == tarea_id)

def marcar_bloqueada(tarea_id: str):
    """
    Sin slots / locked-jobs: temporal, entra en cooldown para no reintentar de inmediato.
    """
    tareas_table.update({"estado": "bloqueada", "fecha": datetime.now().isoformat()}, Tarea.id == tarea_id)

def guardar_sesion(tareas_completadas: int, ganancias: float):
    sesiones_table.insert({
        "fecha": datetime.now().isoformat(),
        "tareas_completadas": tareas_completadas,
        "ganancias": ganancias
    })
    logger.info(f"Sesión guardada: {tareas_completadas} tareas, ${ganancias:.2f}")

def resumen_ganancias() -> dict:
    hoy = datetime.now().strftime("%Y-%m-%d")
    todas = sesiones_table.all()
    total = sum(s["ganancias"] for s in todas)
    hoy_total = sum(s["ganancias"] for s in todas if s["fecha"].startswith(hoy))
    return {"total": total, "hoy": hoy_total}
#!/usr/bin/env python3
"""Utilidad para limpiar TinyDB del bot Microworkers.

Uso:
  python3 scripts/clean_db.py                 # limpia tareas procesadas
  python3 scripts/clean_db.py --all           # reset total (tareas + sesiones)
  python3 scripts/clean_db.py --only completada fallida
"""

from __future__ import annotations

import argparse
from pathlib import Path
from tinydb import TinyDB, Query

DEFAULT_DB_PATH = Path("data/tasks.json")
ESTADOS_VALIDOS = {"completada", "fallida", "pendiente", "bloqueada"}


def limpiar_procesadas(db: TinyDB, estados: list[str]) -> int:
    tareas = db.table("tareas")
    Tarea = Query()
    docs = tareas.search(Tarea.estado.one_of(estados))
    if not docs:
        return 0
    tareas.remove(doc_ids=[d.doc_id for d in docs])
    return len(docs)


def reset_total(db: TinyDB) -> tuple[int, int]:
    tareas = db.table("tareas")
    sesiones = db.table("sesiones")
    cant_tareas = len(tareas)
    cant_sesiones = len(sesiones)
    tareas.truncate()
    sesiones.truncate()
    return cant_tareas, cant_sesiones


def main() -> int:
    parser = argparse.ArgumentParser(description="Limpiar TinyDB del bot")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Ruta del tasks.json")
    parser.add_argument("--all", action="store_true", help="Reset total (tareas + sesiones)")
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="ESTADO",
        help="Estados a limpiar (por defecto: completada fallida pendiente bloqueada)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    estados = args.only or ["completada", "fallida", "pendiente", "bloqueada"]
    invalidos = [e for e in estados if e not in ESTADOS_VALIDOS]
    if invalidos:
        parser.error(f"Estados inválidos: {', '.join(invalidos)}")

    db = TinyDB(str(db_path))
    try:
        if args.all:
            t, s = reset_total(db)
            print(f"OK: reset total. tareas={t} sesiones={s}")
        else:
            n = limpiar_procesadas(db, estados)
            print(f"OK: limpiadas {n} tareas con estados: {', '.join(estados)}")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

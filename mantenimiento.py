import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

EQUIPMENT_SEARCH_FIELDS = {
    "nombre": "nombre",
    "marca": "marca",
    "modelo": "modelo",
    "serial": "serial",
    "usuario": "usuario",
    "area": "area",
    "estado": "estado",
    "sede_nombre": "sede_nombre",
    "fecha_registro": "fecha_registro",
}

FINAL_MAINTENANCE_STATUSES = (
    "Buen estado",
    "Requiere repuesto",
    "Revisión adicional",
    "Reparado",
    "Dañado",
    "Obsoleto",
)


def get_database_path():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        data_directory = Path(local_app_data) / "GestorPC"
    else:
        data_directory = Path.home() / ".gestor_pc"

    return data_directory / "mantenimiento.db"


def _connect(database_path=None):
    path = Path(database_path) if database_path else get_database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def _database(database_path=None):
    connection = _connect(database_path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(database_path=None):
    with _database(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sedes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
                fecha_creacion TEXT
            );

            CREATE TABLE IF NOT EXISTS equipos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                marca TEXT,
                modelo TEXT,
                serial TEXT UNIQUE,
                usuario TEXT,
                area TEXT,
                fecha_registro TEXT,
                estado TEXT,
                sede_id INTEGER,
                FOREIGN KEY(sede_id) REFERENCES sedes(id)
            );

            CREATE TABLE IF NOT EXISTS mantenimientos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipo_id INTEGER,
                fecha TEXT,
                tipo TEXT,
                descripcion TEXT,
                tecnico TEXT,
                costo REAL,
                proximo_mantenimiento TEXT,
                estado_final TEXT,
                FOREIGN KEY(equipo_id) REFERENCES equipos(id)
            );
            """
        )
        maintenance_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(mantenimientos)").fetchall()
        }
        if "estado_final" not in maintenance_columns:
            connection.execute(
                "ALTER TABLE mantenimientos ADD COLUMN estado_final TEXT"
            )
        sede_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(equipos)").fetchall()
        }
        if "sede_id" not in sede_columns:
            connection.execute("ALTER TABLE equipos ADD COLUMN sede_id INTEGER")

        seed_location_names = ("Bogotá", "Medellín", "Cali")
        for seed_location_name in seed_location_names:
            connection.execute(
                """
                INSERT OR IGNORE INTO sedes(nombre, fecha_creacion)
                VALUES (?, ?)
                """,
                (seed_location_name, date.today().isoformat()),
            )


def list_equipment(database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        return connection.execute(
            """
            SELECT equipos.*, sedes.nombre AS sede_nombre
            FROM equipos
            LEFT JOIN sedes ON sedes.id = equipos.sede_id
            ORDER BY equipos.nombre COLLATE NOCASE, equipos.id
            """
        ).fetchall()


def filter_equipment(query="", database_path=None, field="all"):
    equipment = list_equipment(database_path)
    query = query.strip().lower()
    if not query:
        return equipment

    if field == "estado":
        return [
            item
            for item in equipment
            if str(item["estado"] or "Activo").strip().lower().startswith(query)
        ]

    column = EQUIPMENT_SEARCH_FIELDS.get(field)
    columns = (
        tuple(EQUIPMENT_SEARCH_FIELDS.values())
        if field == "all" or column is None
        else (column,)
    )
    return [
        item
        for item in equipment
        if any(
            query in str(item[column]).lower()
            for column in columns
            if item[column] is not None
        )
    ]


def list_locations(database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        return connection.execute(
            """
            SELECT sedes.*,
                   COUNT(equipos.id) AS equipment_count
            FROM sedes
            LEFT JOIN equipos ON equipos.sede_id = sedes.id
            GROUP BY sedes.id
            ORDER BY sedes.nombre COLLATE NOCASE
            """
        ).fetchall()


def add_location(nombre, database_path=None):
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre de la sede es obligatorio.")
    if len(nombre) > 100:
        raise ValueError("El nombre de la sede no puede superar 100 caracteres.")
    initialize_database(database_path)
    try:
        with _database(database_path) as connection:
            connection.execute(
                """
                INSERT INTO sedes(nombre, fecha_creacion)
                VALUES (?, ?)
                """,
                (nombre, date.today().isoformat()),
            )
    except sqlite3.IntegrityError as error:
        raise ValueError("Ya existe una sede con ese nombre.") from error


def location_exists(location_id, database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        return connection.execute(
            "SELECT 1 FROM sedes WHERE id = ?", (location_id,)
        ).fetchone() is not None


def count_equipment_registered_in_month(year, month, database_path=None):
    try:
        start = date(int(year), int(month), 1)
    except (TypeError, ValueError) as error:
        raise ValueError("Selecciona un mes válido.") from error
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)

    initialize_database(database_path)
    with _database(database_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM equipos
            WHERE fecha_registro >= ? AND fecha_registro < ?
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()
    return row["total"]


def add_equipment(
    nombre,
    marca="",
    modelo="",
    serial="",
    usuario="",
    area="",
    sede_id=None,
    fecha_registro=None,
    database_path=None,
):
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del equipo es obligatorio.")

    initialize_database(database_path)
    if sede_id:
        try:
            sede_id = int(sede_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Selecciona una sede válida.") from error
        if not location_exists(sede_id, database_path):
            raise ValueError("Selecciona una sede existente.")
    registration_date = (fecha_registro or date.today().isoformat()).strip()
    try:
        parsed_registration_date = date.fromisoformat(registration_date)
    except ValueError as error:
        raise ValueError("La fecha de registro debe usar el formato AAAA-MM-DD.") from error
    if parsed_registration_date.isoformat() != registration_date:
        raise ValueError("La fecha de registro debe usar el formato AAAA-MM-DD.")
    if parsed_registration_date > date.today():
        raise ValueError("Fecha inválida.")
    try:
        with _database(database_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO equipos(
                    nombre, marca, modelo, serial, usuario, area, fecha_registro, estado,
                    sede_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    nombre,
                    marca.strip(),
                    modelo.strip(),
                    serial.strip() or None,
                    usuario.strip(),
                    area.strip(),
                    registration_date,
                    "Activo",
                    sede_id,
                ),
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError as error:
        if "serial" in str(error).lower():
            raise ValueError("Ya existe un equipo con ese número de serie.") from error
        raise


def update_equipment_status(equipment_id, estado, database_path=None):
    states = {"activo": "Activo", "inactivo": "Inactivo"}
    normalized_status = states.get((estado or "").strip().lower())
    if normalized_status is None:
        raise ValueError("El estado debe ser Activo o Inactivo.")

    initialize_database(database_path)
    with _database(database_path) as connection:
        cursor = connection.execute(
            "UPDATE equipos SET estado = ? WHERE id = ?",
            (normalized_status, equipment_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("No se encontró el equipo seleccionado.")


def delete_equipment(equipment_id, database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        maintenance_count = connection.execute(
            "SELECT COUNT(*) FROM mantenimientos WHERE equipo_id = ?",
            (equipment_id,),
        ).fetchone()[0]
        if maintenance_count:
            raise ValueError(
                "No se puede eliminar un equipo que tiene historial de mantenimiento."
            )
        cursor = connection.execute("DELETE FROM equipos WHERE id = ?", (equipment_id,))
        if cursor.rowcount == 0:
            raise ValueError("No se encontró el equipo seleccionado.")


def add_maintenance(
    equipment_id,
    tipo,
    descripcion,
    tecnico,
    costo,
    proximo_mantenimiento="",
    database_path=None,
    fecha=None,
    estado_final="",
):
    tipo = tipo.strip()
    if not tipo:
        raise ValueError("El tipo de mantenimiento es obligatorio.")

    if costo is None:
        validated_cost = None
    else:
        try:
            validated_cost = float(costo)
        except (TypeError, ValueError) as error:
            raise ValueError("El costo debe ser un número válido.") from error
        if validated_cost < 0:
            raise ValueError("El costo no puede ser negativo.")

    maintenance_date = (fecha or date.today().isoformat()).strip()
    try:
        parsed_maintenance_date = date.fromisoformat(maintenance_date)
    except ValueError as error:
        raise ValueError(
            "La fecha de mantenimiento debe usar el formato AAAA-MM-DD."
        ) from error
    if parsed_maintenance_date.isoformat() != maintenance_date:
        raise ValueError(
            "La fecha de mantenimiento debe usar el formato AAAA-MM-DD."
        )

    next_date = proximo_mantenimiento.strip()
    if next_date:
        try:
            datetime.strptime(next_date, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError("La próxima fecha debe usar el formato AAAA-MM-DD.") from error

    final_status = (estado_final or "").strip()
    if final_status and final_status not in FINAL_MAINTENANCE_STATUSES:
        raise ValueError("Selecciona un estado final válido.")

    initialize_database(database_path)
    with _database(database_path) as connection:
        equipment = connection.execute(
            "SELECT 1 FROM equipos WHERE id = ?", (equipment_id,)
        ).fetchone()
        if not equipment:
            raise ValueError("Selecciona un equipo existente.")
        cursor = connection.execute(
            """
            INSERT INTO mantenimientos(
                equipo_id, fecha, tipo, descripcion, tecnico, costo,
                proximo_mantenimiento, estado_final
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                equipment_id,
                maintenance_date,
                tipo,
                descripcion.strip(),
                tecnico.strip(),
                validated_cost,
                next_date or None,
                final_status or None,
            ),
        )
        return cursor.lastrowid


def delete_maintenance(maintenance_id, database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        cursor = connection.execute(
            "DELETE FROM mantenimientos WHERE id = ?", (maintenance_id,)
        )
        if cursor.rowcount == 0:
            raise ValueError("No se encontró el mantenimiento seleccionado.")


def get_monthly_summary(year, month, database_path=None):
    try:
        start = date(int(year), int(month), 1)
    except (TypeError, ValueError) as error:
        raise ValueError("Selecciona un mes válido.") from error
    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)

    initialize_database(database_path)
    with _database(database_path) as connection:
        summary = connection.execute(
            """
            SELECT COUNT(DISTINCT equipo_id) AS equipos_revisados,
                   COUNT(*) AS mantenimientos_registrados
            FROM mantenimientos
            WHERE fecha >= ? AND fecha < ?
              AND (proximo_mantenimiento IS NULL OR proximo_mantenimiento = '')
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        records = connection.execute(
            """
            SELECT mantenimientos.*, equipos.nombre AS equipo
            FROM mantenimientos
            INNER JOIN equipos ON equipos.id = mantenimientos.equipo_id
            WHERE mantenimientos.fecha >= ? AND mantenimientos.fecha < ?
              AND (mantenimientos.proximo_mantenimiento IS NULL
                   OR mantenimientos.proximo_mantenimiento = '')
            ORDER BY mantenimientos.fecha DESC, mantenimientos.id DESC
            """,
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    return {
        "year": start.year,
        "month": start.month,
        "equipos_revisados": summary["equipos_revisados"],
        "mantenimientos_registrados": summary["mantenimientos_registrados"],
        "records": records,
    }


def get_maintenance_history(equipment_id, database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        return connection.execute(
            """
            SELECT * FROM mantenimientos
            WHERE equipo_id = ?
              AND (proximo_mantenimiento IS NULL OR proximo_mantenimiento = '')
            ORDER BY fecha DESC, id DESC
            """,
            (equipment_id,),
        ).fetchall()


def list_maintenance(database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        return connection.execute(
            """
            SELECT mantenimientos.*, equipos.nombre AS equipo
            FROM mantenimientos
            INNER JOIN equipos ON equipos.id = mantenimientos.equipo_id
            ORDER BY mantenimientos.fecha DESC, mantenimientos.id DESC
            """
        ).fetchall()


def list_completed_maintenances(database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        return connection.execute(
            """
            SELECT mantenimientos.*, equipos.nombre AS equipo
            FROM mantenimientos
            INNER JOIN equipos ON equipos.id = mantenimientos.equipo_id
            WHERE mantenimientos.proximo_mantenimiento IS NULL
               OR mantenimientos.proximo_mantenimiento = ''
            ORDER BY mantenimientos.fecha DESC, mantenimientos.id DESC
            """
        ).fetchall()


def get_overdue_maintenance(database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT equipos.nombre, mantenimientos.proximo_mantenimiento,
                   mantenimientos.tipo, mantenimientos.id
            FROM mantenimientos
            INNER JOIN equipos ON equipos.id = mantenimientos.equipo_id
            WHERE mantenimientos.proximo_mantenimiento IS NOT NULL
              AND mantenimientos.proximo_mantenimiento != ''
            ORDER BY mantenimientos.proximo_mantenimiento
            """
        ).fetchall()

    overdue = []
    for row in rows:
        try:
            due_date = date.fromisoformat(row["proximo_mantenimiento"])
        except ValueError as error:
            raise ValueError(
                f"La fecha del mantenimiento {row['id']} no es válida."
            ) from error
        if due_date <= date.today():
            overdue.append(row)
    return overdue


def count_scheduled_maintenance(database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM mantenimientos
            WHERE proximo_mantenimiento IS NOT NULL
              AND proximo_mantenimiento != ''
              AND proximo_mantenimiento >= ?
            """,
            (date.today().isoformat(),),
        ).fetchone()
    return row["total"]


def list_scheduled_maintenances(database_path=None):
    initialize_database(database_path)
    with _database(database_path) as connection:
        return connection.execute(
            """
            SELECT mantenimientos.*, equipos.nombre AS equipo,
                   equipos.serial, equipos.sede_id,
                   CASE WHEN EXISTS(
                       SELECT 1
                       FROM mantenimientos AS completed
                       WHERE (
                           completed.proximo_mantenimiento IS NULL
                           OR completed.proximo_mantenimiento = ''
                       )
                         AND completed.equipo_id = mantenimientos.equipo_id
                           AND completed.fecha = mantenimientos.proximo_mantenimiento
                   ) THEN 'Completo' ELSE 'Pendiente' END AS estado_programacion
            FROM mantenimientos
            INNER JOIN equipos ON equipos.id = mantenimientos.equipo_id
            WHERE mantenimientos.proximo_mantenimiento IS NOT NULL
              AND mantenimientos.proximo_mantenimiento != ''
            ORDER BY mantenimientos.proximo_mantenimiento,
                     equipos.nombre COLLATE NOCASE,
                     mantenimientos.id DESC
            """
        ).fetchall()


def get_maintenance_notifications(database_path=None):
    today = date.today()
    reminder_date = today + timedelta(days=7)

    initialize_database(database_path)
    with _database(database_path) as connection:
        scheduled = connection.execute(
            """
            SELECT equipos.nombre, mantenimientos.tipo,
                   mantenimientos.proximo_mantenimiento
            FROM mantenimientos
            INNER JOIN equipos ON equipos.id = mantenimientos.equipo_id
            WHERE mantenimientos.proximo_mantenimiento = ?
            ORDER BY equipos.nombre COLLATE NOCASE
            """,
            (reminder_date.isoformat(),),
        ).fetchall()

    return [
        {
            "kind": "info",
            "title": "Recordatorio de mantenimiento",
            "detail": (
                f"{item['nombre']} · {item['tipo']} · "
                f"{item['proximo_mantenimiento']}"
            ),
        }
        for item in scheduled
    ]


def get_recent_activity(database_path=None):
    today = date.today()
    activity = []
    initialize_database(database_path)

    with _database(database_path) as connection:
        latest_maintenance = connection.execute(
            """
            SELECT mantenimientos.*, equipos.nombre AS equipo
            FROM mantenimientos
            INNER JOIN equipos ON equipos.id = mantenimientos.equipo_id
            WHERE mantenimientos.proximo_mantenimiento IS NULL
               OR mantenimientos.proximo_mantenimiento = ''
            ORDER BY mantenimientos.fecha DESC, mantenimientos.id DESC
            LIMIT 1
            """
        ).fetchone()
        latest_equipment = connection.execute(
            """
            SELECT * FROM equipos
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        scheduled = connection.execute(
            """
            SELECT equipos.nombre, mantenimientos.proximo_mantenimiento,
                   mantenimientos.tipo
            FROM mantenimientos
            INNER JOIN equipos ON equipos.id = mantenimientos.equipo_id
            WHERE mantenimientos.proximo_mantenimiento > ?
            ORDER BY mantenimientos.proximo_mantenimiento, mantenimientos.id
            LIMIT 1
            """,
            (today.isoformat(),),
        ).fetchone()

    if latest_maintenance:
        activity.append({
            "kind": "success",
            "title": f"{latest_maintenance['equipo']} revisado",
            "detail": f"{latest_maintenance['tipo']} · {latest_maintenance['fecha']}",
            "date": latest_maintenance["fecha"],
        })
    if latest_equipment:
        registration_date = latest_equipment["fecha_registro"] or ""
        activity.append({
            "kind": "success",
            "title": f"{latest_equipment['nombre']} registrado",
            "detail": f"Alta en inventario · {registration_date or '—'}",
            "date": registration_date,
        })
    if scheduled:
        activity.append({
            "kind": "warning",
            "title": "Mantenimiento programado",
            "detail": f"{scheduled['nombre']} · {scheduled['proximo_mantenimiento']}",
            "date": scheduled["proximo_mantenimiento"],
        })

    overdue = get_overdue_maintenance(database_path)
    if overdue:
        item = overdue[0]
        activity.append({
            "kind": "warning",
            "title": f"{item['nombre']} requiere atención",
            "detail": f"Mantenimiento vencido · {item['proximo_mantenimiento']}",
            "date": item["proximo_mantenimiento"],
        })

    activity.sort(key=lambda item: item["date"], reverse=True)
    return activity[:2]


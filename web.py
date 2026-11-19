import hmac
import os
import re
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import mantenimiento


def _normalize_search_text(value):
    normalized = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    )


@contextmanager
def _user_database(database_path):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _validated_username(value):
    username = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,64}", username):
        raise ValueError(
            "El usuario debe tener entre 3 y 64 caracteres: letras, números, punto, guion o @."
        )
    return username


def _validated_location_id(value, connection):
    if not value:
        raise ValueError("La sede es obligatoria.")
    try:
        location_id = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Selecciona una sede válida.") from error
    if connection.execute(
        "SELECT 1 FROM sedes WHERE id = ?", (location_id,)
    ).fetchone() is None:
        raise ValueError("Selecciona una sede válida.")
    return location_id


def _validated_password(value):
    if len(value) < 12:
        raise ValueError("La contraseña debe tener al menos 12 caracteres.")
    return value


def _validated_display_name(value):
    display_name = value.strip()
    if not display_name:
        raise ValueError("El nombre visible es obligatorio.")
    if len(display_name) > 80:
        raise ValueError("El nombre visible no puede superar 80 caracteres.")
    return display_name


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("GESTOR_PC_SECRET_KEY"),
        BOOTSTRAP_USERNAME=os.environ.get("GESTOR_PC_USERNAME"),
        BOOTSTRAP_PASSWORD=os.environ.get("GESTOR_PC_PASSWORD"),
        DATABASE_PATH=os.environ.get("GESTOR_PC_DB"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("GESTOR_PC_COOKIE_SECURE", "").lower()
        in {"1", "true", "yes"},
    )
    if config:
        app.config.update(config)

    if not app.config["SECRET_KEY"] or len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("Configura GESTOR_PC_SECRET_KEY con al menos 32 caracteres.")
    if not app.config["DATABASE_PATH"]:
        app.config["DATABASE_PATH"] = str(mantenimiento.get_database_path())
    app.config["DATABASE_PATH"] = Path(app.config["DATABASE_PATH"])
    mantenimiento.initialize_database(app.config["DATABASE_PATH"])
    with _user_database(app.config["DATABASE_PATH"]) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                session_version INTEGER NOT NULL DEFAULT 0,
                sede_id INTEGER REFERENCES sedes(id)
            )
            """
        )
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(usuarios)").fetchall()
        }
        if "display_name" not in existing_columns:
            connection.execute(
                "ALTER TABLE usuarios ADD COLUMN display_name TEXT NOT NULL DEFAULT ''"
            )
            connection.execute(
                "UPDATE usuarios SET display_name = CASE "
                "WHEN role = 'admin' THEN 'Carlos Gómez' ELSE username END "
                "WHERE display_name = ''"
            )
        if "sede_id" not in existing_columns:
            connection.execute(
                "ALTER TABLE usuarios ADD COLUMN sede_id INTEGER REFERENCES sedes(id)"
            )
        else:
            connection.execute(
                "UPDATE usuarios SET display_name = CASE "
                "WHEN role = 'admin' THEN 'Carlos Gómez' ELSE username END "
                "WHERE display_name = ''"
            )
        user_count = connection.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        if user_count == 0:
            if not app.config["BOOTSTRAP_USERNAME"] or not app.config["BOOTSTRAP_PASSWORD"]:
                raise RuntimeError(
                    "La primera vez configura GESTOR_PC_USERNAME y "
                    "GESTOR_PC_PASSWORD para crear la cuenta administradora."
                )
            username = _validated_username(app.config["BOOTSTRAP_USERNAME"])
            password = _validated_password(app.config["BOOTSTRAP_PASSWORD"])
            connection.execute(
                """
                INSERT INTO usuarios(username, display_name, password_hash, role)
                VALUES (?, 'Carlos Gómez', ?, 'admin')
                """,
                (username, generate_password_hash(password)),
            )

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not getattr(g, "user", None):
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)

        return wrapped

    def admin_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] != "admin":
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    @app.before_request
    def load_authenticated_user():
        user_id = session.get("user_id")
        if user_id is None:
            g.user = None
            return
        with _user_database(app.config["DATABASE_PATH"]) as connection:
            user = connection.execute(
                "SELECT * FROM usuarios WHERE id = ?", (user_id,)
            ).fetchone()
        if (
            user is None
            or not user["is_active"]
            or user["session_version"] != session.get("session_version")
        ):
            session.clear()
            g.user = None
            flash("Tu sesión expiró o la cuenta fue desactivada. Inicia sesión de nuevo.", "error")
            return
        g.user = user

    @app.before_request
    def protect_post_requests():
        if request.method == "POST":
            submitted_token = request.form.get("csrf_token", "")
            expected_token = session.get("csrf_token", "")
            if not expected_token or not hmac.compare_digest(
                submitted_token, expected_token
            ):
                abort(400, description="El formulario expiró. Recarga la página e inténtalo de nuevo.")

    @app.context_processor
    def add_template_context():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return {
            "csrf_token": session["csrf_token"],
            "current_user": getattr(g, "user", None),
            "today": date.today().isoformat(),
        }

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        return response

    @app.errorhandler(sqlite3.Error)
    def handle_database_error(error):
        app.logger.exception("Error de base de datos", exc_info=error)
        return render_template(
            "error.html",
            title="Error de base de datos",
            message="No se pudo completar la operación. Revisa el registro del servidor.",
        ), 500

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            with _user_database(app.config["DATABASE_PATH"]) as connection:
                user = connection.execute(
                    "SELECT * FROM usuarios WHERE username = ? COLLATE NOCASE",
                    (username,),
                ).fetchone()
            if (
                user
                and user["is_active"]
                and check_password_hash(user["password_hash"], password)
            ):
                session.clear()
                session["user_id"] = user["id"]
                session["session_version"] = user["session_version"]
                flash("Sesión iniciada.", "success")
                next_url = request.args.get("next", "")
                if next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect(url_for("dashboard"))
            flash("Usuario o contraseña incorrectos.", "error")
        return render_template("login.html")

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        flash("Sesión cerrada.", "success")
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def dashboard():
        database_path = app.config["DATABASE_PATH"]
        today = date.today()
        selected_month = request.args.get("month", today.strftime("%Y-%m"))
        try:
            selected_date = date.fromisoformat(f"{selected_month}-01")
            if selected_date.strftime("%Y-%m") != selected_month:
                raise ValueError("Selecciona un mes válido.")
            monthly_summary = mantenimiento.get_monthly_summary(
                selected_date.year,
                selected_date.month,
                database_path,
            )
        except ValueError as error:
            flash(str(error), "error")
            selected_month = today.strftime("%Y-%m")
            monthly_summary = mantenimiento.get_monthly_summary(
                today.year, today.month, database_path
            )
        try:
            equipment = mantenimiento.list_equipment(database_path)
            maintenance = mantenimiento.list_completed_maintenances(database_path)
            overdue = mantenimiento.get_overdue_maintenance(database_path)
            recent_activity = mantenimiento.get_recent_activity(database_path)
            notifications = mantenimiento.get_maintenance_notifications(database_path)
            scheduled_maintenance = mantenimiento.count_scheduled_maintenance(database_path)
            equipment_added_this_month = mantenimiento.count_equipment_registered_in_month(
                today.year, today.month, database_path
            )
        except ValueError as error:
            app.logger.exception("No se pudieron cargar las alertas", exc_info=error)
            flash(str(error), "error")
            overdue = []
            recent_activity = []
            notifications = []
            scheduled_maintenance = 0
            equipment_added_this_month = 0
        recent_equipment = sorted(
            equipment,
            key=lambda item: item["id"],
            reverse=True,
        )[:5]
        return render_template(
            "dashboard.html",
            equipment=equipment,
            recent_equipment=recent_equipment,
            maintenance=maintenance,
            overdue=overdue,
            monthly_summary=monthly_summary,
            selected_month=selected_month,
            equipment_added_this_month=equipment_added_this_month,
            recent_activity=recent_activity,
            notifications=notifications,
            scheduled_maintenance=scheduled_maintenance,
        )

    @app.get("/equipment")
    @login_required
    def equipment_list():
        query = request.args.get("q", "").strip()
        field = request.args.get("field", "nombre")
        if field not in mantenimiento.EQUIPMENT_SEARCH_FIELDS:
            field = "nombre"
        sort = request.args.get("sort", "")
        if sort != "fecha_registro":
            sort = ""
        order = request.args.get("order", "desc")
        if order not in {"asc", "desc"}:
            order = "desc"
        equipment = mantenimiento.filter_equipment(
            query,
            app.config["DATABASE_PATH"],
            field,
        )
        if sort:
            equipment.sort(
                key=lambda item: (item["fecha_registro"] or "", item["id"]),
                reverse=order == "desc",
            )
        locations = mantenimiento.list_locations(app.config["DATABASE_PATH"])
        maintenance = mantenimiento.list_maintenance(app.config["DATABASE_PATH"])
        equipment_with_history = {row["equipo_id"] for row in maintenance}
        return render_template(
            "equipment_list.html",
            equipment=equipment,
            equipment_with_history=equipment_with_history,
            locations=locations,
            query=query,
            field=field,
            sort=sort,
            order=order,
            total_equipment=mantenimiento.list_equipment(app.config["DATABASE_PATH"]),
        )

    @app.get("/maintenances/scheduled")
    @login_required
    def scheduled_maintenances():
        scheduled = mantenimiento.list_scheduled_maintenances(app.config["DATABASE_PATH"])
        return render_template(
            "scheduled_maintenances.html",
            maintenance=scheduled,
            today=date.today().isoformat(),
        )

    @app.post("/maintenance/<int:maintenance_id>/delete")
    @login_required
    def remove_maintenance(maintenance_id):
        try:
            mantenimiento.delete_maintenance(
                maintenance_id,
                app.config["DATABASE_PATH"],
            )
        except ValueError as error:
            flash(str(error), "error")
        else:
            flash("Mantenimiento eliminado correctamente.", "success")
        return_to = request.form.get("return_to", "scheduled_maintenances")
        if return_to not in {"scheduled_maintenances", "completed_maintenances"}:
            return_to = "scheduled_maintenances"
        return redirect(url_for(return_to))

    @app.get("/maintenances/completed")
    @login_required
    def completed_maintenances():
        completed = mantenimiento.list_completed_maintenances(
            app.config["DATABASE_PATH"]
        )
        return render_template("completed_maintenances.html", maintenance=completed)

    @app.get("/users")
    @admin_required
    def users():
        with _user_database(app.config["DATABASE_PATH"]) as connection:
            accounts = connection.execute(
                """
                SELECT usuarios.id, usuarios.username, usuarios.display_name,
                       usuarios.role, usuarios.is_active, usuarios.sede_id,
                       sedes.nombre AS sede_nombre
                FROM usuarios
                LEFT JOIN sedes ON sedes.id = usuarios.sede_id
                ORDER BY usuarios.username COLLATE NOCASE
                """
            ).fetchall()
        locations = mantenimiento.list_locations(app.config["DATABASE_PATH"])
        return render_template(
            "users.html",
            accounts=accounts,
            locations=locations,
        )

    @app.get("/search")
    @login_required
    def search():
        query = request.args.get("q", "").strip()
        equipment_results = []
        maintenance_results = []
        account_results = []

        if query:
            normalized_query = _normalize_search_text(query)
            escaped_query = (
                normalized_query.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{escaped_query}%"

            with mantenimiento._database(app.config["DATABASE_PATH"]) as connection:
                connection.create_function(
                    "normalize_search",
                    1,
                    _normalize_search_text,
                )
                equipment_results = connection.execute(
                    """
                    SELECT equipos.*, sedes.nombre AS sede_nombre
                    FROM equipos
                    LEFT JOIN sedes ON sedes.id = equipos.sede_id
                    WHERE normalize_search(equipos.nombre) LIKE ? ESCAPE '\\'
                       OR normalize_search(equipos.marca) LIKE ? ESCAPE '\\'
                       OR normalize_search(equipos.modelo) LIKE ? ESCAPE '\\'
                       OR normalize_search(equipos.serial) LIKE ? ESCAPE '\\'
                       OR normalize_search(equipos.usuario) LIKE ? ESCAPE '\\'
                       OR normalize_search(equipos.area) LIKE ? ESCAPE '\\'
                       OR normalize_search(equipos.estado) LIKE ? ESCAPE '\\'
                       OR normalize_search(sedes.nombre) LIKE ? ESCAPE '\\'
                    ORDER BY equipos.nombre COLLATE NOCASE
                    LIMIT 25
                    """,
                    (pattern,) * 8,
                ).fetchall()
                maintenance_results = connection.execute(
                    """
                    SELECT mantenimientos.*, equipos.nombre AS equipo
                    FROM mantenimientos
                    INNER JOIN equipos ON equipos.id = mantenimientos.equipo_id
                    WHERE normalize_search(mantenimientos.fecha) LIKE ? ESCAPE '\\'
                       OR normalize_search(mantenimientos.tipo) LIKE ? ESCAPE '\\'
                       OR normalize_search(mantenimientos.descripcion) LIKE ? ESCAPE '\\'
                       OR normalize_search(mantenimientos.tecnico) LIKE ? ESCAPE '\\'
                       OR normalize_search(mantenimientos.proximo_mantenimiento) LIKE ? ESCAPE '\\'
                       OR normalize_search(equipos.nombre) LIKE ? ESCAPE '\\'
                       OR normalize_search(equipos.serial) LIKE ? ESCAPE '\\'
                    ORDER BY mantenimientos.fecha DESC, mantenimientos.id DESC
                    LIMIT 25
                    """,
                    (pattern,) * 7,
                ).fetchall()

            if g.user["role"] == "admin":
                with _user_database(app.config["DATABASE_PATH"]) as connection:
                    connection.create_function(
                        "normalize_search",
                        1,
                        _normalize_search_text,
                    )
                    account_results = connection.execute(
                        """
                        SELECT id, username, display_name, role, is_active
                        FROM usuarios
                        WHERE normalize_search(username) LIKE ? ESCAPE '\\'
                        ORDER BY username COLLATE NOCASE
                        LIMIT 25
                        """,
                        (pattern,),
                    ).fetchall()

        return render_template(
            "search.html",
            query=query,
            equipment_results=equipment_results,
            maintenance_results=maintenance_results,
            account_results=account_results,
        )

    @app.post("/users/new")
    @admin_required
    def create_user():
        try:
            username = _validated_username(request.form.get("username", ""))
            display_name = _validated_display_name(request.form.get("display_name", "") or request.form.get("username", ""))
            password = _validated_password(request.form.get("password", ""))
            with _user_database(app.config["DATABASE_PATH"]) as connection:
                sede_id = _validated_location_id(
                    request.form.get("sede_id", "").strip(),
                    connection,
                )
                connection.execute(
                    """
                    INSERT INTO usuarios(
                        username, display_name, password_hash, role, sede_id
                    )
                    VALUES (?, ?, ?, 'user', ?)
                    """,
                    (
                        username,
                        display_name,
                        generate_password_hash(password),
                        sede_id,
                    ),
                )
        except ValueError as error:
            flash(str(error), "error")
        except sqlite3.IntegrityError:
            flash("Ya existe una cuenta con ese nombre de usuario.", "error")
        else:
            flash("Cuenta creada correctamente.", "success")
        return redirect(url_for("users"))

    @app.post("/users/<int:user_id>/update")
    @admin_required
    def update_user(user_id):
        try:
            username = _validated_username(request.form.get("username", ""))
            display_name = _validated_display_name(request.form.get("display_name", "") or request.form.get("username", ""))
            with _user_database(app.config["DATABASE_PATH"]) as connection:
                sede_id = _validated_location_id(
                    request.form.get("sede_id", "").strip(),
                    connection,
                )
                cursor = connection.execute(
                    """
                    UPDATE usuarios
                    SET username = ?, display_name = ?, sede_id = ?
                    WHERE id = ?
                    """,
                    (username, display_name, sede_id, user_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError("No se encontró esa cuenta.")
        except ValueError as error:
            flash(str(error), "error")
        except sqlite3.IntegrityError:
            flash("Ya existe una cuenta con ese nombre de usuario.", "error")
        else:
            if user_id == g.user["id"]:
                session["user_id"] = user_id
            flash("Nombre de usuario actualizado.", "success")
        return redirect(url_for("users"))

    @app.post("/users/<int:user_id>/password")
    @admin_required
    def reset_user_password(user_id):
        try:
            password = _validated_password(request.form.get("password", ""))
            with _user_database(app.config["DATABASE_PATH"]) as connection:
                cursor = connection.execute(
                    """
                    UPDATE usuarios
                    SET password_hash = ?, session_version = session_version + 1
                    WHERE id = ?
                    """,
                    (generate_password_hash(password), user_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError("No se encontró esa cuenta.")
                new_version = connection.execute(
                    "SELECT session_version FROM usuarios WHERE id = ?", (user_id,)
                ).fetchone()["session_version"]
        except ValueError as error:
            flash(str(error), "error")
        else:
            if user_id == g.user["id"]:
                session["session_version"] = new_version
            flash("Contraseña actualizada; se cerraron las otras sesiones de esa cuenta.", "success")
        return redirect(url_for("users"))

    @app.post("/users/<int:user_id>/toggle")
    @admin_required
    def toggle_user(user_id):
        if user_id == g.user["id"]:
            flash("No puedes desactivar tu propia cuenta.", "error")
            return redirect(url_for("users"))
        try:
            with _user_database(app.config["DATABASE_PATH"]) as connection:
                connection.execute("BEGIN IMMEDIATE")
                user = connection.execute(
                    "SELECT role, is_active FROM usuarios WHERE id = ?", (user_id,)
                ).fetchone()
                if user is None:
                    raise ValueError("No se encontró esa cuenta.")
                if user["role"] == "admin" and user["is_active"]:
                    active_admins = connection.execute(
                        """
                        SELECT COUNT(*) FROM usuarios
                        WHERE role = 'admin' AND is_active = 1
                        """
                    ).fetchone()[0]
                    if active_admins <= 1:
                        raise ValueError("No puedes desactivar al último administrador activo.")
                new_active_state = 0 if user["is_active"] else 1
                connection.execute(
                    """
                    UPDATE usuarios
                    SET is_active = ?, session_version = session_version + 1
                    WHERE id = ?
                    """,
                    (new_active_state, user_id),
                )
        except ValueError as error:
            flash(str(error), "error")
        else:
            flash(
                "Cuenta activada." if new_active_state else "Cuenta desactivada.",
                "success",
            )
        return redirect(url_for("users"))

    @app.route("/locations", methods=["GET", "POST"])
    @admin_required
    def locations():
        if request.method == "POST":
            try:
                mantenimiento.add_location(
                    request.form.get("nombre", ""),
                    app.config["DATABASE_PATH"],
                )
            except ValueError as error:
                flash(str(error), "error")
            else:
                flash("Sede creada correctamente.", "success")
                return redirect(url_for("locations"))
        return render_template(
            "locations.html",
            locations=mantenimiento.list_locations(app.config["DATABASE_PATH"]),
        )

    @app.get("/locations/<int:location_id>")
    @admin_required
    def location_detail(location_id):
        locations = mantenimiento.list_locations(app.config["DATABASE_PATH"])
        location = next(
            (item for item in locations if item["id"] == location_id),
            None,
        )
        if location is None:
            abort(404)
        equipment = [
            item
            for item in mantenimiento.list_equipment(app.config["DATABASE_PATH"])
            if item["sede_id"] == location_id
        ]
        with _user_database(app.config["DATABASE_PATH"]) as connection:
            users = connection.execute(
                """
                SELECT id, username, display_name, role, is_active
                FROM usuarios
                WHERE sede_id = ?
                ORDER BY display_name COLLATE NOCASE, username COLLATE NOCASE
                """,
                (location_id,),
            ).fetchall()
        return render_template(
            "location_detail.html",
            location=location,
            users=users,
            equipment=equipment,
        )

    @app.route("/account/password", methods=["GET", "POST"])
    @login_required
    def change_own_password():
        if request.method == "POST":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("password", "")
            confirmation = request.form.get("confirmation", "")
            if not check_password_hash(g.user["password_hash"], current_password):
                flash("La contraseña actual no es correcta.", "error")
            elif new_password != confirmation:
                flash("Las contraseñas nuevas no coinciden.", "error")
            else:
                try:
                    _validated_password(new_password)
                except ValueError as error:
                    flash(str(error), "error")
                else:
                    with _user_database(app.config["DATABASE_PATH"]) as connection:
                        connection.execute(
                            """
                            UPDATE usuarios
                            SET password_hash = ?, session_version = session_version + 1
                            WHERE id = ?
                            """,
                            (generate_password_hash(new_password), g.user["id"]),
                        )
                    session["session_version"] += 1
                    flash("Tu contraseña se actualizó correctamente.", "success")
                    return redirect(url_for("dashboard"))
        return render_template("account_password.html")

    @app.route("/equipment/new", methods=["GET", "POST"])
    @login_required
    def new_equipment():
        if request.method == "POST":
            try:
                required_fields = {
                    "nombre": "Concepto",
                    "marca": "Marca",
                    "modelo": "Modelo",
                    "serial": "Número de serie",
                    "usuario": "Usuario responsable",
                    "area": "Área",
                    "sede_id": "Sede",
                    "fecha_registro": "Fecha de registro",
                }
                missing_fields = [
                    label
                    for field, label in required_fields.items()
                    if not request.form.get(field, "").strip()
                ]
                if missing_fields:
                    raise ValueError(
                        "Todos los campos son obligatorios. Faltan: "
                        + ", ".join(missing_fields)
                        + "."
                    )
                mantenimiento.add_equipment(
                    nombre=request.form.get("nombre", ""),
                    marca=request.form.get("marca", ""),
                    modelo=request.form.get("modelo", ""),
                    serial=request.form.get("serial", ""),
                    usuario=request.form.get("usuario", ""),
                    area=request.form.get("area", ""),
                    sede_id=request.form.get("sede_id", "") or None,
                    fecha_registro=request.form.get("fecha_registro", ""),
                    database_path=app.config["DATABASE_PATH"],
                )
            except ValueError as error:
                flash(str(error), "error")
            else:
                flash("Equipo registrado correctamente.", "success")
                return redirect(url_for("dashboard"))
        return render_template(
            "equipment_form.html",
            locations=mantenimiento.list_locations(app.config["DATABASE_PATH"]),
        )

    @app.post("/equipment/<int:equipment_id>/delete")
    @login_required
    def remove_equipment(equipment_id):
        try:
            mantenimiento.delete_equipment(equipment_id, app.config["DATABASE_PATH"])
        except ValueError as error:
            flash(str(error), "error")
        else:
            flash("Equipo eliminado.", "success")
        return redirect(url_for("equipment_list"))

    @app.post("/equipment/<int:equipment_id>/status")
    @login_required
    def update_equipment_status(equipment_id):
        try:
            mantenimiento.update_equipment_status(
                equipment_id,
                request.form.get("estado", ""),
                app.config["DATABASE_PATH"],
            )
        except ValueError as error:
            flash(str(error), "error")
        else:
            flash("Estado del equipo actualizado.", "success")

        query = request.form.get("q", "").strip()
        field = request.form.get("field", "nombre")
        if field not in mantenimiento.EQUIPMENT_SEARCH_FIELDS:
            field = "nombre"
        return redirect(
            url_for(
                "equipment_list",
                q=query or None,
                field=field,
            )
        )

    @app.get("/equipment/<int:equipment_id>/history")
    @login_required
    def equipment_history(equipment_id):
        database_path = app.config["DATABASE_PATH"]
        equipment = next(
            (
                row
                for row in mantenimiento.list_equipment(database_path)
                if row["id"] == equipment_id
            ),
            None,
        )
        if equipment is None:
            abort(404)
        history = mantenimiento.get_maintenance_history(equipment_id, database_path)
        return render_template("history.html", equipment=equipment, history=history)

    @app.route("/maintenance/new", methods=["GET", "POST"])
    @login_required
    def new_maintenance():
        database_path = app.config["DATABASE_PATH"]
        equipment = mantenimiento.list_equipment(database_path)
        from_completed = request.args.get("source") == "completed"
        if request.method == "POST":
            maintenance_date = (
                request.form.get("fecha", "").strip() if from_completed else ""
            )
            final_status = (
                request.form.get("estado_final", "").strip() if from_completed else ""
            )
            next_maintenance = (
                "" if from_completed
                else request.form.get("proximo_mantenimiento", "").strip()
            )
            try:
                equipment_id = int(request.form.get("equipo_id", ""))
                selected_equipment = next(
                    (item for item in equipment if item["id"] == equipment_id),
                    None,
                )
                if selected_equipment is None:
                    raise ValueError("Selecciona un equipo existente.")
                if (selected_equipment["estado"] or "").lower() == "inactivo":
                    raise ValueError("Fecha inválida.")
                if from_completed:
                    if not maintenance_date:
                        raise ValueError("La fecha de mantenimiento es obligatoria.")
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
                    if parsed_maintenance_date < date.today():
                        raise ValueError("Fecha inválida.")
                else:
                    maintenance_date = (
                        selected_equipment["fecha_registro"] or date.today().isoformat()
                    )
                if from_completed and not final_status:
                    raise ValueError("El estado final es obligatorio.")
                if not next_maintenance:
                    if not from_completed:
                        raise ValueError("El próximo mantenimiento es obligatorio.")
                else:
                    try:
                        parsed_next_maintenance = date.fromisoformat(next_maintenance)
                    except ValueError as error:
                        raise ValueError(
                            "La próxima fecha debe usar el formato AAAA-MM-DD."
                        ) from error
                    if parsed_next_maintenance.isoformat() != next_maintenance:
                        raise ValueError(
                            "La próxima fecha debe usar el formato AAAA-MM-DD."
                        )
                    if parsed_next_maintenance <= date.today():
                        raise ValueError("Fecha inválida.")
                technician = request.form.get("tecnico", "").strip()
                if not technician:
                    raise ValueError("El técnico responsable es obligatorio.")
                mantenimiento.add_maintenance(
                    equipment_id=equipment_id,
                    fecha=maintenance_date,
                    tipo=request.form.get("tipo", ""),
                    descripcion=(
                        request.form.get("descripcion", "") if from_completed else ""
                    ),
                    tecnico=technician,
                    costo=request.form.get("costo", "") if from_completed else None,
                    proximo_mantenimiento=next_maintenance,
                    database_path=database_path,
                    estado_final=final_status,
                )
            except ValueError as error:
                flash(str(error), "error")
            else:
                flash("Mantenimiento registrado correctamente.", "success")
                destination = "completed_maintenances" if from_completed else "scheduled_maintenances"
                return redirect(url_for(destination))
        return render_template(
            "maintenance_form.html",
            equipment=equipment,
            from_completed=from_completed,
            final_maintenance_statuses=mantenimiento.FINAL_MAINTENANCE_STATUSES,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=os.environ.get("GESTOR_PC_HOST", "127.0.0.1"),
        port=int(os.environ.get("GESTOR_PC_PORT", "5000")),
        debug=False,
    )

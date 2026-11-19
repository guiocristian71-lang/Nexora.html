import os
import re
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("GESTOR_PC_SECRET_KEY", "test-secret-key-that-is-long-enough")
os.environ.setdefault("GESTOR_PC_USERNAME", "test-admin")
os.environ.setdefault("GESTOR_PC_PASSWORD", "test-password-long")
bootstrap_directory = tempfile.TemporaryDirectory()
os.environ.setdefault(
    "GESTOR_PC_DB", str(Path(bootstrap_directory.name) / "bootstrap.db")
)

import web


class WebAppTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = web.create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret-key-that-is-long-enough",
                "BOOTSTRAP_USERNAME": "test-admin",
                "BOOTSTRAP_PASSWORD": "test-password-long",
                "DATABASE_PATH": Path(self.temp_dir.name) / "web.db",
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _csrf_token(self, response):
        match = re.search(
            r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True)
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def _login(self, username="test-admin", password="test-password-long", client=None):
        client = client or self.client
        login_page = client.get("/login")
        token = self._csrf_token(login_page)
        return client.post(
            "/login",
            data={
                "csrf_token": token,
                "username": username,
                "password": password,
            },
            follow_redirects=True,
        )

    def _account_id(self, username):
        connection = sqlite3.connect(self.app.config["DATABASE_PATH"])
        try:
            row = connection.execute(
                "SELECT id FROM usuarios WHERE username = ?", (username,)
            ).fetchone()
        finally:
            connection.close()
        return row[0]

    def test_dashboard_requires_login(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_workspace_has_three_independent_maintenance_and_equipment_views(self):
        self._login()

        equipment_page = self.client.get("/equipment")
        scheduled_page = self.client.get("/maintenances/scheduled")
        completed_page = self.client.get("/maintenances/completed")

        self.assertEqual(equipment_page.status_code, 200)
        self.assertEqual(scheduled_page.status_code, 200)
        self.assertEqual(completed_page.status_code, 200)
        self.assertIn("Inventario de equipos", equipment_page.get_data(as_text=True))
        self.assertIn("Mantenimientos programados", scheduled_page.get_data(as_text=True))
        self.assertIn("Mantenimientos realizados", completed_page.get_data(as_text=True))
        self.assertIn(
            'href="/maintenance/new?source=completed"',
            completed_page.get_data(as_text=True),
        )

    def test_dashboard_places_recent_activity_below_monthly_report(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Laptop HP",
            database_path=self.app.config["DATABASE_PATH"],
        )
        web.mantenimiento.add_maintenance(
            equipment_id=equipment_id,
            fecha=date.today().isoformat(),
            tipo="Preventivo",
            descripcion="Revisión",
            tecnico="Alex",
            costo="25",
            database_path=self.app.config["DATABASE_PATH"],
        )

        html = self.client.get("/").get_data(as_text=True)
        report_pos = html.find('class="panel monthly-panel"')
        activity_pos = html.find('class="panel recent-activity-panel"')

        self.assertGreater(report_pos, -1)
        self.assertGreater(activity_pos, report_pos)
        self.assertIn("Actividad reciente", html)
        self.assertIn("Laptop HP revisado", html)

    def test_dashboard_recent_activity_shows_only_two_latest_items(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Equipo reciente",
            fecha_registro=(date.today() - timedelta(days=2)).isoformat(),
            database_path=self.app.config["DATABASE_PATH"],
        )
        web.mantenimiento.add_maintenance(
            equipment_id=equipment_id,
            fecha=date.today().isoformat(),
            tipo="Preventivo",
            descripcion="Revisión",
            tecnico="Alex",
            costo="25",
            database_path=self.app.config["DATABASE_PATH"],
        )
        web.mantenimiento.add_maintenance(
            equipment_id=equipment_id,
            tipo="Preventivo",
            descripcion="",
            tecnico="Alex",
            costo=None,
            proximo_mantenimiento=(date.today() + timedelta(days=1)).isoformat(),
            database_path=self.app.config["DATABASE_PATH"],
        )

        response = self.client.get("/")
        activity = response.get_data(as_text=True).split(
            '<section class="panel recent-activity-panel">', 1
        )[1].split("</section>", 1)[0]

        self.assertEqual(activity.count('<article class="recent-activity-item'), 2)
        self.assertIn("Mantenimiento programado", activity)
        self.assertIn("Equipo reciente revisado", activity)
        self.assertNotIn("Equipo reciente registrado", activity)

    def test_dashboard_shows_equipment_added_this_month(self):
        self._login()
        web.mantenimiento.add_equipment(
            "PC actual",
            database_path=self.app.config["DATABASE_PATH"],
        )

        response = self.client.get("/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("+1 este mes", html)

    def test_dashboard_updates_show_latest_equipment_and_its_registration_date(self):
        self._login()
        web.mantenimiento.add_equipment(
            "Anterior",
            fecha_registro=date.today().isoformat(),
            database_path=self.app.config["DATABASE_PATH"],
        )
        latest_date = (date.today() - timedelta(days=10)).isoformat()
        web.mantenimiento.add_equipment(
            "Último concepto",
            fecha_registro=latest_date,
            database_path=self.app.config["DATABASE_PATH"],
        )

        response = self.client.get("/")
        activity = response.get_data(as_text=True).split(
            '<section class="panel recent-activity-panel">', 1
        )[1].split("</section>", 1)[0]

        self.assertIn("Último concepto registrado", activity)
        self.assertIn(f"Alta en inventario · {latest_date}", activity)
        self.assertNotIn("Anterior registrado", activity)

    def test_dashboard_shows_only_five_most_recent_equipment(self):
        self._login()
        for number in range(1, 8):
            web.mantenimiento.add_equipment(
                f"Equipo {number}",
                database_path=self.app.config["DATABASE_PATH"],
            )

        response = self.client.get("/")
        html = response.get_data(as_text=True)
        inventory = html.split('<section class="panel" id="inventory">', 1)[1].split(
            "</section>", 1
        )[0]

        self.assertIn("5 recientes", inventory)
        self.assertIn("Registros recientes", inventory)
        self.assertIn("Ver todos", inventory)
        self.assertNotIn("Eliminar", inventory)
        self.assertNotIn("Equipo 1", inventory)
        self.assertNotIn("Equipo 2", inventory)
        for number in range(3, 8):
            self.assertIn(f"Equipo {number}", inventory)
        positions = [inventory.index(f"Equipo {number}") for number in range(7, 2, -1)]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("<strong>7</strong>", html)

    def test_dashboard_report_can_filter_by_month(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "PC reporte",
            database_path=self.app.config["DATABASE_PATH"],
        )
        selected_date = date.today().replace(day=1).isoformat()
        web.mantenimiento.add_maintenance(
            equipment_id=equipment_id,
            fecha=selected_date,
            tipo="Preventivo",
            descripcion="Primera revisión",
            tecnico="Ana",
            costo="10",
            database_path=self.app.config["DATABASE_PATH"],
        )

        month = selected_date[:7]
        response = self.client.get(f"/?month={month}")
        html = response.get_data(as_text=True)
        self.assertIn("Revisiones por mes", html)
        self.assertIn("PC reporte", html)

    def test_dashboard_replaces_critical_alerts_with_completed_and_scheduled(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Servidor",
            database_path=self.app.config["DATABASE_PATH"],
        )
        web.mantenimiento.add_maintenance(
            equipment_id=equipment_id,
            fecha=date.today().isoformat(),
            tipo="Preventivo",
            descripcion="Revisión",
            tecnico="Carlos",
            costo="25",
            proximo_mantenimiento=(date.today() + timedelta(days=2)).isoformat(),
            database_path=self.app.config["DATABASE_PATH"],
        )

        html = self.client.get("/").get_data(as_text=True)
        self.assertIn(">Mantenimientos realizados<", html)
        self.assertIn(">Mantenimientos programados<", html)
        self.assertIn("Registro histórico", html)
        self.assertNotIn("Alertas críticas", html)

    def test_scheduled_maintenance_is_listed_and_can_be_deleted(self):
        self._login()
        registration_date = date.today() + timedelta(days=3)
        connection = sqlite3.connect(self.app.config["DATABASE_PATH"])
        try:
            cursor = connection.execute(
                """
                INSERT INTO equipos(nombre, serial, fecha_registro, estado)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "Equipo programado",
                    "SER-PROG-01",
                    registration_date.isoformat(),
                    "Activo",
                ),
            )
            equipment_id = cursor.lastrowid
            connection.commit()
        finally:
            connection.close()
        maintenance_form = self.client.get("/maintenance/new")
        form_html = maintenance_form.get_data(as_text=True)
        self.assertIn("<title>Programar mantenimiento · Nexora</title>", form_html)
        self.assertIn("<h1>Programar mantenimiento</h1>", form_html)
        self.assertNotIn("Registra cuándo se realizó el trabajo", form_html)
        self.assertIn("Programa la próxima fecha", form_html)
        self.assertIn('name="proximo_mantenimiento"', form_html)
        self.assertIn('name="proximo_mantenimiento" type="date" required', form_html)
        self.assertIn("Próximo mantenimiento *", form_html)
        self.assertNotIn('name="descripcion"', form_html)
        self.assertNotIn('name="fecha"', form_html)
        self.assertIn('data-maintenance-dependent', form_html)
        self.assertIn("Fecha de ingreso *", form_html)
        self.assertIn("data-maintenance-review-date", form_html)
        self.assertIn(
            'id="maintenance-review-date" type="text" value="" readonly',
            form_html,
        )
        self.assertNotIn("Costo total", form_html)
        self.assertNotIn('name="costo"', form_html)
        self.assertIn(">Guardar</button>", form_html)
        self.assertIn('name="tecnico"', form_html)
        self.assertIn('maxlength="150" required', form_html)
        self.assertIn('<option value="Preventivo"', form_html)
        self.assertNotIn('<option value="Correctivo"', form_html)
        self.assertNotIn('name="estado_final"', form_html)
        self.assertIn("Equipo programado · SER-PROG-01", form_html)
        response = self.client.post(
            "/maintenance/new",
            data={
                "csrf_token": self._csrf_token(maintenance_form),
                "equipo_id": str(equipment_id),
                "fecha": date.today().isoformat(),
                "tipo": "Preventivo",
                "tecnico": "Alex",
                "descripcion": "Campo exclusivo de mantenimientos realizados",
                "estado_final": "Reparado",
                "proximo_mantenimiento": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/maintenances/scheduled")

        scheduled_page = self.client.get("/maintenances/scheduled")
        scheduled_html = scheduled_page.get_data(as_text=True)
        maintenance = web.mantenimiento.list_scheduled_maintenances(
            self.app.config["DATABASE_PATH"]
        )[0]
        self.assertEqual(maintenance["fecha"], registration_date.isoformat())
        self.assertIsNone(maintenance["costo"])
        self.assertIsNone(maintenance["estado_final"])
        self.assertEqual(maintenance["descripcion"], "")
        self.assertIn("Equipo programado", scheduled_html)
        self.assertIn("SER-PROG-01", scheduled_html)
        self.assertIn("data-confirm-delete", scheduled_html)
        self.assertIn("también su registro del historial", scheduled_html)
        completed_page = self.client.get("/maintenances/completed")
        completed_html = completed_page.get_data(as_text=True)
        self.assertNotIn("Equipo programado", completed_html)
        self.assertIn("No hay mantenimientos realizados registrados.", completed_html)
        self.assertNotIn("data-confirm-delete", completed_html)

        deletion_response = self.client.post(
            f"/maintenance/{maintenance['id']}/delete",
            data={
                "csrf_token": self._csrf_token(scheduled_page),
                "return_to": "scheduled_maintenances",
            },
        )

        self.assertEqual(deletion_response.status_code, 302)
        self.assertEqual(
            deletion_response.headers["Location"],
            "/maintenances/scheduled",
        )
        deleted_html = self.client.get(deletion_response.headers["Location"]).get_data(
            as_text=True
        )
        self.assertIn("Mantenimiento eliminado correctamente.", deleted_html)
        self.assertIn("No hay mantenimientos programados.", deleted_html)
        completed_after_delete = self.client.get(
            "/maintenances/completed"
        ).get_data(as_text=True)
        self.assertIn("No hay mantenimientos realizados registrados.", completed_after_delete)
        self.assertEqual(
            web.mantenimiento.get_maintenance_history(
                equipment_id,
                self.app.config["DATABASE_PATH"],
            ),
            [],
        )

    def test_maintenance_requires_date(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Equipo sin fecha de mantenimiento",
            database_path=self.app.config["DATABASE_PATH"],
        )
        maintenance_form = self.client.get("/maintenance/new?source=completed")
        response = self.client.post(
            "/maintenance/new?source=completed",
            data={
                "csrf_token": self._csrf_token(maintenance_form),
                "equipo_id": str(equipment_id),
                "tipo": "Preventivo",
                "costo": "25",
                "tecnico": "Alex",
                "proximo_mantenimiento": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "La fecha de mantenimiento es obligatoria.",
            response.get_data(as_text=True),
        )

    def test_scheduled_status_is_complete_when_equipment_and_date_match(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Equipo con estado",
            database_path=self.app.config["DATABASE_PATH"],
        )
        maintenance_date = date.today().isoformat()
        scheduled_date = (date.today() + timedelta(days=30)).isoformat()
        scheduled_id = web.mantenimiento.add_maintenance(
            equipment_id,
            "Preventivo",
            "",
            "Técnico planificado",
            None,
            proximo_mantenimiento=scheduled_date,
            database_path=self.app.config["DATABASE_PATH"],
            fecha=maintenance_date,
        )
        pending_id = web.mantenimiento.add_maintenance(
            equipment_id,
            "Preventivo",
            "",
            "Técnico planificado",
            None,
            proximo_mantenimiento=(date.today() + timedelta(days=31)).isoformat(),
            database_path=self.app.config["DATABASE_PATH"],
            fecha=(date.today() + timedelta(days=1)).isoformat(),
        )
        other_equipment_id = web.mantenimiento.add_equipment(
            "Equipo diferente",
            database_path=self.app.config["DATABASE_PATH"],
        )
        other_equipment_maintenance_id = web.mantenimiento.add_maintenance(
            other_equipment_id,
            "Preventivo",
            "",
            "Técnico planificado",
            None,
            proximo_mantenimiento=scheduled_date,
            database_path=self.app.config["DATABASE_PATH"],
            fecha=maintenance_date,
        )

        maintenance_form = self.client.get("/maintenance/new?source=completed")
        response = self.client.post(
            "/maintenance/new?source=completed",
            data={
                "csrf_token": self._csrf_token(maintenance_form),
                "equipo_id": str(equipment_id),
                "fecha": scheduled_date,
                "tipo": "Correctivo",
                "estado_final": "Reparado",
                "costo": "60",
                "tecnico": "Técnico ejecutor",
                "descripcion": "Limpieza",
            },
        )

        self.assertEqual(response.status_code, 302)
        scheduled = {
            item["id"]: item
            for item in web.mantenimiento.list_scheduled_maintenances(
                self.app.config["DATABASE_PATH"]
            )
        }
        self.assertEqual(scheduled[scheduled_id]["estado_programacion"], "Completo")
        self.assertEqual(scheduled[pending_id]["estado_programacion"], "Pendiente")
        self.assertEqual(
            scheduled[other_equipment_maintenance_id]["estado_programacion"],
            "Pendiente",
        )
        scheduled_page = self.client.get("/maintenances/scheduled")
        scheduled_html = scheduled_page.get_data(as_text=True)
        self.assertIn("<th>Estado</th>", scheduled_html)
        self.assertIn("Completo", scheduled_html)
        self.assertIn("Pendiente", scheduled_html)

    def test_maintenance_requires_final_status(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Equipo sin estado final",
            database_path=self.app.config["DATABASE_PATH"],
        )
        maintenance_form = self.client.get("/maintenance/new?source=completed")
        response = self.client.post(
            "/maintenance/new?source=completed",
            data={
                "csrf_token": self._csrf_token(maintenance_form),
                "equipo_id": str(equipment_id),
                "fecha": date.today().isoformat(),
                "tipo": "Preventivo",
                "costo": "25",
                "tecnico": "Alex",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "El estado final es obligatorio.",
            response.get_data(as_text=True),
        )

    def test_inactive_equipment_shows_invalid_date_and_cannot_be_scheduled(self):
        self._login()
        connection = sqlite3.connect(self.app.config["DATABASE_PATH"])
        try:
            cursor = connection.execute(
                """
                INSERT INTO equipos(nombre, serial, fecha_registro, estado)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "Equipo inactivo",
                    "SER-INACT-01",
                    date.today().isoformat(),
                    "Inactivo",
                ),
            )
            equipment_id = cursor.lastrowid
            connection.commit()
        finally:
            connection.close()

        maintenance_form = self.client.get("/maintenance/new")
        self.assertIn(
            "Equipo inactivo · SER-INACT-01 · Inactivo",
            maintenance_form.get_data(as_text=True),
        )
        self.assertIn(
            "data-maintenance-review-date",
            maintenance_form.get_data(as_text=True),
        )
        response = self.client.post(
            "/maintenance/new",
            data={
                "csrf_token": self._csrf_token(maintenance_form),
                "equipo_id": str(equipment_id),
                "fecha": date.today().isoformat(),
                "tipo": "Preventivo",
                "costo": "25",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Fecha inválida.", response.get_data(as_text=True))
        self.assertEqual(
            web.mantenimiento.get_maintenance_history(
                equipment_id,
                self.app.config["DATABASE_PATH"],
            ),
            [],
        )

    def test_maintenance_requires_responsible_technician(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Equipo sin técnico",
            database_path=self.app.config["DATABASE_PATH"],
        )
        maintenance_form = self.client.get("/maintenance/new?source=completed")
        response = self.client.post(
            "/maintenance/new?source=completed",
            data={
                "csrf_token": self._csrf_token(maintenance_form),
                "equipo_id": str(equipment_id),
                "tipo": "Preventivo",
                "costo": "25",
                "tecnico": "   ",
                "fecha": date.today().isoformat(),
                "estado_final": "Buen estado",
                "proximo_mantenimiento": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "El técnico responsable es obligatorio.",
            response.get_data(as_text=True),
        )
        self.assertEqual(
            web.mantenimiento.get_maintenance_history(
                equipment_id,
                self.app.config["DATABASE_PATH"],
            ),
            [],
        )

    def test_maintenance_requires_next_maintenance_date(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Equipo sin próxima fecha",
            database_path=self.app.config["DATABASE_PATH"],
        )
        maintenance_form = self.client.get("/maintenance/new")
        response = self.client.post(
            "/maintenance/new",
            data={
                "csrf_token": self._csrf_token(maintenance_form),
                "equipo_id": str(equipment_id),
                "fecha": date.today().isoformat(),
                "tipo": "Preventivo",
                "costo": "25",
                "tecnico": "Alex",
                "proximo_mantenimiento": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "El próximo mantenimiento es obligatorio.",
            response.get_data(as_text=True),
        )
        self.assertEqual(
            web.mantenimiento.get_maintenance_history(
                equipment_id,
                self.app.config["DATABASE_PATH"],
            ),
            [],
        )

    def test_maintenance_rejects_past_maintenance_date(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Equipo con fecha pasada",
            database_path=self.app.config["DATABASE_PATH"],
        )
        maintenance_form = self.client.get("/maintenance/new?source=completed")
        response = self.client.post(
            "/maintenance/new?source=completed",
            data={
                "csrf_token": self._csrf_token(maintenance_form),
                "equipo_id": str(equipment_id),
                "fecha": (date.today() - timedelta(days=1)).isoformat(),
                "estado_final": "Buen estado",
                "tipo": "Preventivo",
                "costo": "25",
                "tecnico": "Alex",
                "proximo_mantenimiento": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Fecha inválida.", response.get_data(as_text=True))
        self.assertEqual(
            web.mantenimiento.get_maintenance_history(
                equipment_id,
                self.app.config["DATABASE_PATH"],
            ),
            [],
        )

    def test_completed_workspace_registers_without_next_maintenance(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Equipo realizado",
            database_path=self.app.config["DATABASE_PATH"],
        )
        maintenance_form = self.client.get("/maintenance/new?source=completed")
        form_html = maintenance_form.get_data(as_text=True)
        self.assertIn("Registrar mantenimiento realizado", form_html)
        self.assertIn('name="fecha" type="date"', form_html)
        self.assertNotIn('name="proximo_mantenimiento"', form_html)
        self.assertIn('<select name="estado_final" required', form_html)
        self.assertIn("Costo total *", form_html)
        self.assertIn('<input name="costo" type="number"', form_html)
        self.assertIn("Descripción (opcional)", form_html)
        self.assertIn('<textarea name="descripcion"', form_html)
        self.assertIn('<option value="Preventivo"', form_html)
        self.assertIn('<option value="Correctivo"', form_html)

        response = self.client.post(
            "/maintenance/new?source=completed",
            data={
                "csrf_token": self._csrf_token(maintenance_form),
                "equipo_id": str(equipment_id),
                "fecha": date.today().isoformat(),
                "estado_final": "Reparado",
                "tipo": "Correctivo",
                "costo": "25",
                "tecnico": "Alex",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/maintenances/completed")
        history = web.mantenimiento.get_maintenance_history(
            equipment_id,
            self.app.config["DATABASE_PATH"],
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["tipo"], "Correctivo")
        self.assertEqual(history[0]["estado_final"], "Reparado")
        self.assertEqual(history[0]["descripcion"], "")
        self.assertIsNone(history[0]["proximo_mantenimiento"])
        completed_page = self.client.get("/maintenances/completed")
        completed_html = completed_page.get_data(as_text=True)
        self.assertIn("<th>Estado final</th>", completed_html)
        self.assertIn("Reparado", completed_html)
        self.assertNotIn("<th>Próximo</th>", completed_html)

    def test_maintenance_rejects_today_or_past_next_date(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Equipo con fecha de mantenimiento inválida",
            database_path=self.app.config["DATABASE_PATH"],
        )
        maintenance_form = self.client.get("/maintenance/new")
        for invalid_date in (
            date.today().isoformat(),
            (date.today() - timedelta(days=1)).isoformat(),
        ):
            with self.subTest(invalid_date=invalid_date):
                response = self.client.post(
                    "/maintenance/new",
                    data={
                        "csrf_token": self._csrf_token(maintenance_form),
                        "equipo_id": str(equipment_id),
                        "fecha": date.today().isoformat(),
                        "tipo": "Preventivo",
                        "costo": "25",
                        "tecnico": "Alex",
                        "proximo_mantenimiento": invalid_date,
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn("Fecha inválida.", response.get_data(as_text=True))
                self.assertEqual(
                    web.mantenimiento.list_scheduled_maintenances(
                        self.app.config["DATABASE_PATH"]
                    ),
                    [],
                )

    def test_equipment_view_filters_shared_data(self):
        self._login()
        location_id = web.mantenimiento.add_location(
            "Bogotá central",
            self.app.config["DATABASE_PATH"],
        )
        locations = web.mantenimiento.list_locations(self.app.config["DATABASE_PATH"])
        bogota = next(
            location for location in locations if location["nombre"] == "Bogotá central"
        )
        web.mantenimiento.add_equipment(
            "Laptop HP",
            marca="HP",
            modelo="ProBook",
            serial="SER-123",
            usuario="Ana Pérez",
            area="Recepción",
            sede_id=bogota["id"],
            database_path=self.app.config["DATABASE_PATH"],
        )

        by_serial = self.client.get("/equipment?q=SER-123&field=serial")
        by_responsible = self.client.get("/equipment?q=Ana&field=usuario")
        by_location = self.client.get("/equipment?q=Bogotá&field=sede_nombre")
        by_wrong_field = self.client.get("/equipment?q=ProBook&field=nombre")
        by_model = self.client.get("/equipment?q=ProBook&field=modelo")
        equipment_page = self.client.get("/equipment")

        self.assertIn("Laptop HP", by_serial.get_data(as_text=True))
        self.assertIn("Laptop HP", by_responsible.get_data(as_text=True))
        self.assertIn("Laptop HP", by_location.get_data(as_text=True))
        self.assertNotIn("Laptop HP", by_wrong_field.get_data(as_text=True))
        self.assertIn("Laptop HP", by_model.get_data(as_text=True))
        self.assertIn('option value="modelo" selected', by_model.get_data(as_text=True))
        self.assertIn("data-spanish-autocorrect", equipment_page.get_data(as_text=True))
        self.assertIn(
            'placeholder="Buscar equipo, serie, responsable..."',
            equipment_page.get_data(as_text=True),
        )
        self.assertIn('aria-label="Borrar búsqueda"', equipment_page.get_data(as_text=True))
        self.assertIn(">Limpiar filtros</a>", equipment_page.get_data(as_text=True))
        self.assertNotIn("Todos los campos", equipment_page.get_data(as_text=True))
        self.assertIn('option value="nombre" selected', equipment_page.get_data(as_text=True))
        self.assertIn("Eliminar", by_serial.get_data(as_text=True))
        self.assertIn("¿Deseas continuar?", by_serial.get_data(as_text=True))
        self.assertIn("Cancelar", by_serial.get_data(as_text=True))
        self.assertIn("data-confirm-delete", by_serial.get_data(as_text=True))
        self.assertNotIn("onsubmit=", by_serial.get_data(as_text=True))

    def test_equipment_list_sorts_by_registration_date_in_both_directions(self):
        self._login()
        today = date.today()
        for name, registration_date in (
            ("Equipo antiguo", (today - timedelta(days=800)).isoformat()),
            ("Equipo medio", (today - timedelta(days=100)).isoformat()),
            ("Equipo reciente", (today - timedelta(days=1)).isoformat()),
        ):
            web.mantenimiento.add_equipment(
                name,
                fecha_registro=registration_date,
                database_path=self.app.config["DATABASE_PATH"],
            )

        newest_first = self.client.get(
            "/equipment?sort=fecha_registro&order=desc"
        ).get_data(as_text=True)
        oldest_first = self.client.get(
            "/equipment?sort=fecha_registro&order=asc"
        ).get_data(as_text=True)
        newest_table = newest_first.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        oldest_table = oldest_first.split("<tbody>", 1)[1].split("</tbody>", 1)[0]

        self.assertLess(
            newest_table.index("Equipo reciente"),
            newest_table.index("Equipo antiguo"),
        )
        self.assertLess(
            oldest_table.index("Equipo antiguo"),
            oldest_table.index("Equipo reciente"),
        )
        self.assertIn("Más reciente primero", newest_first)
        self.assertIn("Más antigua primero", oldest_first)

    def test_equipment_status_can_be_changed_to_active_or_inactive(self):
        self._login()
        active_equipment_id = web.mantenimiento.add_equipment(
            "Equipo activo",
            database_path=self.app.config["DATABASE_PATH"],
        )
        inactive_equipment_id = web.mantenimiento.add_equipment(
            "Equipo inactivo",
            database_path=self.app.config["DATABASE_PATH"],
        )
        equipment_page = self.client.get("/equipment")
        token = self._csrf_token(equipment_page)

        response = self.client.post(
            f"/equipment/{inactive_equipment_id}/status",
            data={"csrf_token": token, "estado": "Inactivo", "field": "all"},
            follow_redirects=True,
        )
        equipment = next(
            item
            for item in web.mantenimiento.list_equipment(
                self.app.config["DATABASE_PATH"]
            )
            if item["id"] == inactive_equipment_id
        )

        self.assertEqual(equipment["estado"], "Inactivo")
        self.assertIn('class="badge badge-red">Inactivo</span>', response.get_data(as_text=True))
        self.assertIn("Estado del equipo actualizado.", response.get_data(as_text=True))
        active_results = self.client.get("/equipment?q=Activo&field=estado").get_data(
            as_text=True
        )
        inactive_results = self.client.get(
            "/equipment?q=Inactivo&field=estado"
        ).get_data(as_text=True)
        self.assertIn("Equipo activo", active_results)
        self.assertNotIn("Equipo inactivo", active_results)
        self.assertIn("Equipo inactivo", inactive_results)
        self.assertNotIn("Equipo activo", inactive_results)

        response = self.client.post(
            f"/equipment/{inactive_equipment_id}/status",
            data={"csrf_token": token, "estado": "Activo", "field": "all"},
            follow_redirects=True,
        )
        equipment = next(
            item
            for item in web.mantenimiento.list_equipment(
                self.app.config["DATABASE_PATH"]
            )
            if item["id"] == inactive_equipment_id
        )
        self.assertEqual(equipment["estado"], "Activo")
        self.assertIn('class="badge badge-green">Activo</span>', response.get_data(as_text=True))

        response = self.client.post(
            f"/equipment/{inactive_equipment_id}/status",
            data={"csrf_token": token, "estado": "Pausado"},
            follow_redirects=True,
        )
        equipment = next(
            item
            for item in web.mantenimiento.list_equipment(
                self.app.config["DATABASE_PATH"]
            )
            if item["id"] == inactive_equipment_id
        )
        self.assertEqual(equipment["estado"], "Activo")
        self.assertIn("El estado debe ser Activo o Inactivo.", response.get_data(as_text=True))

    def test_equipment_registration_accepts_custom_registration_date(self):
        self._login()
        registration_date = (date.today() - timedelta(days=3)).isoformat()
        equipment_id = web.mantenimiento.add_equipment(
            "Impresora",
            fecha_registro=registration_date,
            database_path=self.app.config["DATABASE_PATH"],
        )
        equipment = web.mantenimiento.list_equipment(
            self.app.config["DATABASE_PATH"]
        )
        selected = next(item for item in equipment if item["id"] == equipment_id)
        self.assertEqual(selected["fecha_registro"], registration_date)

    def test_equipment_registration_uses_custom_calendar(self):
        self._login()

        response = self.client.get("/equipment/new")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-date-picker', html)
        self.assertIn('data-calendar-days', html)
        self.assertIn('aria-label="Abrir calendario"', html)
        self.assertNotIn('name="fecha_registro" type="date"', html)

    def test_equipment_registration_requires_every_field(self):
        self._login()
        token = self._csrf_token(self.client.get("/equipment/new"))
        location = web.mantenimiento.list_locations(
            self.app.config["DATABASE_PATH"]
        )[0]
        complete_form = {
            "csrf_token": token,
            "nombre": "Equipo obligatorio",
            "marca": "Marca",
            "modelo": "Modelo",
            "serial": "SER-REQ-001",
            "usuario": "Responsable",
            "area": "Área",
            "sede_id": str(location["id"]),
            "fecha_registro": date.today().isoformat(),
        }

        for field in (
            "nombre",
            "marca",
            "modelo",
            "serial",
            "usuario",
            "area",
            "sede_id",
            "fecha_registro",
        ):
            with self.subTest(field=field):
                form_data = {**complete_form, field: ""}
                response = self.client.post("/equipment/new", data=form_data)
                self.assertEqual(response.status_code, 200)
                self.assertIn("Todos los campos son obligatorios", response.get_data(as_text=True))
                self.assertEqual(
                    web.mantenimiento.list_equipment(
                        self.app.config["DATABASE_PATH"]
                    ),
                    [],
                )

    def test_equipment_registration_rejects_future_date(self):
        self._login()
        token = self._csrf_token(self.client.get("/equipment/new"))
        location = web.mantenimiento.list_locations(
            self.app.config["DATABASE_PATH"]
        )[0]
        response = self.client.post(
            "/equipment/new",
            data={
                "csrf_token": token,
                "nombre": "Equipo futuro",
                "marca": "Marca",
                "modelo": "Modelo",
                "serial": "SER-FUT-001",
                "usuario": "Responsable",
                "area": "Área",
                "sede_id": str(location["id"]),
                "fecha_registro": (date.today() + timedelta(days=1)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Fecha inválida.", response.get_data(as_text=True))
        self.assertEqual(
            web.mantenimiento.list_equipment(self.app.config["DATABASE_PATH"]),
            [],
        )

    def test_locations_are_connected_to_equipment_counts(self):
        self._login()
        web.mantenimiento.add_location("Barranquilla", self.app.config["DATABASE_PATH"])
        locations = web.mantenimiento.list_locations(self.app.config["DATABASE_PATH"])
        barranquilla = next(
            location for location in locations if location["nombre"] == "Barranquilla"
        )
        web.mantenimiento.add_equipment(
            "PC sede",
            sede_id=barranquilla["id"],
            database_path=self.app.config["DATABASE_PATH"],
        )

        locations = web.mantenimiento.list_locations(self.app.config["DATABASE_PATH"])
        barranquilla = next(
            location for location in locations if location["nombre"] == "Barranquilla"
        )
        self.assertEqual(barranquilla["equipment_count"], 1)

        page = self.client.get("/locations")
        html = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Barranquilla", html)
        self.assertIn("<strong>1</strong>", html)
        self.assertIn("equipo registrado", html)

    def test_location_detail_shows_users_and_equipment(self):
        self._login()
        web.mantenimiento.add_location(
            "Bogotá detalle",
            self.app.config["DATABASE_PATH"],
        )
        location_id = next(
            item["id"]
            for item in web.mantenimiento.list_locations(
                self.app.config["DATABASE_PATH"]
            )
            if item["nombre"] == "Bogotá detalle"
        )
        equipment_id = web.mantenimiento.add_equipment(
            "Laptop de soporte",
            usuario="Ana Pérez",
            area="Tecnología",
            sede_id=location_id,
            database_path=self.app.config["DATABASE_PATH"],
        )
        users_page = self.client.get("/users")
        response = self.client.post(
            "/users/new",
            data={
                "csrf_token": self._csrf_token(users_page),
                "username": "tecnico.bogota",
                "display_name": "Técnico Bogotá",
                "password": "temporary-password",
                "sede_id": str(location_id),
            },
            follow_redirects=True,
        )
        self.assertIn("Cuenta creada correctamente", response.get_data(as_text=True))

        detail = self.client.get(f"/locations/{location_id}")
        html = detail.get_data(as_text=True)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("Técnicos de la sede", html)
        self.assertIn("Técnico Bogotá", html)
        self.assertIn("Equipos de la sede", html)
        self.assertIn("Laptop de soporte", html)
        self.assertIn("Ana Pérez", html)
        self.assertIn("Tecnología", html)

    def test_global_search_finds_equipment_maintenance_and_users(self):
        self._login()
        web.mantenimiento.add_equipment(
            "PC recepción",
            marca="Dell",
            usuario="Ana",
            database_path=self.app.config["DATABASE_PATH"],
        )
        equipment = web.mantenimiento.list_equipment(self.app.config["DATABASE_PATH"])[0]
        web.mantenimiento.add_maintenance(
            equipment_id=equipment["id"],
            fecha=date.today().isoformat(),
            tipo="Preventivo",
            descripcion="Revisión mensual",
            tecnico="Carlos",
            costo="20",
            database_path=self.app.config["DATABASE_PATH"],
        )

        response = self.client.get("/search?q=RECEPCION")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("PC recepción", html)
        self.assertEqual(html.count('class="panel search-panel"'), 2)
        self.assertNotIn("ADMINISTRACIÓN", html)

        response = self.client.get("/search?q=REVISION")
        html = response.get_data(as_text=True)
        self.assertIn("Revisión mensual", html)

        response = self.client.get("/search?q=cArLoS")
        self.assertIn("Carlos", response.get_data(as_text=True))

        response = self.client.get("/search?q=TEST-ADMIN")
        html = response.get_data(as_text=True)
        self.assertIn("test-admin", html)
        self.assertEqual(html.count('class="panel search-panel"'), 1)

        response = self.client.get("/search?q=sin-coincidencias-123")
        html = response.get_data(as_text=True)
        self.assertEqual(html.count('class="panel search-panel"'), 0)
        self.assertIn("No se encontraron coincidencias.", html)

    def test_login_and_equipment_maintenance_flow(self):
        response = self._login()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Aún no hay equipos", response.get_data(as_text=True))

        token = self._csrf_token(response)
        response = self.client.post(
            "/equipment/new",
            data={
                "csrf_token": token,
                "nombre": "PC recepción",
                "marca": "Dell",
                "modelo": "OptiPlex",
                "serial": "WEB-001",
                "usuario": "Ana",
                "area": "Recepción",
                "sede_id": str(
                    web.mantenimiento.list_locations(
                        self.app.config["DATABASE_PATH"]
                    )[0]["id"]
                ),
                "fecha_registro": date.today().isoformat(),
            },
            follow_redirects=True,
        )
        self.assertIn("PC recepción", response.get_data(as_text=True))

        equipment_id = self.client.get("/").status_code
        self.assertEqual(equipment_id, 200)
        equipment = web.mantenimiento.list_equipment(self.app.config["DATABASE_PATH"])[0]

        maintenance_form = self.client.get("/maintenance/new")
        token = self._csrf_token(maintenance_form)
        review_date = date.today().isoformat()
        response = self.client.post(
            "/maintenance/new",
            data={
                "csrf_token": token,
                "equipo_id": str(equipment["id"]),
                "fecha": review_date,
                "tipo": "Preventivo",
                "costo": "35.50",
                "tecnico": "Alex",
                "proximo_mantenimiento": (
                    date.today() + timedelta(days=7)
                ).isoformat(),
                "descripcion": "Limpieza",
            },
            follow_redirects=True,
        )
        self.assertIn(
            "Mantenimiento registrado correctamente", response.get_data(as_text=True)
        )
        self.assertIn("Preventivo", response.get_data(as_text=True))
        report = self.client.get(f"/?month={review_date[:7]}")
        report_html = report.get_data(as_text=True)
        self.assertIn("Equipos distintos revisados", report_html)
        self.assertRegex(
            report_html,
            r'class="monthly-stat">.*?<strong>0</strong>',
        )
        self.assertNotIn("PC recepción revisado", report_html)

    def test_completed_maintenance_accepts_future_date(self):
        self._login()
        registration_date = (date.today() - timedelta(days=1)).isoformat()
        equipment_id = web.mantenimiento.add_equipment(
            "PC futura",
            fecha_registro=registration_date,
            database_path=self.app.config["DATABASE_PATH"],
        )
        maintenance_form = self.client.get("/maintenance/new?source=completed")
        future_date = (date.today() + timedelta(days=1)).isoformat()
        response = self.client.post(
            "/maintenance/new?source=completed",
            data={
                "csrf_token": self._csrf_token(maintenance_form),
                "equipo_id": str(equipment_id),
                "fecha": future_date,
                "estado_final": "Buen estado",
                "tipo": "Preventivo",
                "costo": "0",
                "tecnico": "Alex",
            },
            follow_redirects=True,
        )

        history = web.mantenimiento.get_maintenance_history(
            equipment_id,
            self.app.config["DATABASE_PATH"],
        )
        self.assertIn("Mantenimiento registrado correctamente.", response.get_data(as_text=True))
        scheduled = web.mantenimiento.list_scheduled_maintenances(
            self.app.config["DATABASE_PATH"]
        )
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["fecha"], future_date)
        self.assertEqual(history[0]["estado_final"], "Buen estado")
        self.assertEqual(scheduled, [])

    def test_post_without_csrf_token_is_rejected(self):
        self._login()

        response = self.client.post("/equipment/new", data={"nombre": "Equipo"})

        self.assertEqual(response.status_code, 400)

    def test_invalid_login_does_not_authenticate(self):
        login_page = self.client.get("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": self._csrf_token(login_page),
                "username": "test-admin",
                "password": "incorrecto",
            },
            follow_redirects=True,
        )

        self.assertIn("Usuario o contraseña incorrectos", response.get_data(as_text=True))
        self.assertIn("/login", self.client.get("/").headers["Location"])

    def test_notification_menu_is_connected_to_real_alerts(self):
        self._login()
        equipment_id = web.mantenimiento.add_equipment(
            "Servidor SRV-01",
            database_path=self.app.config["DATABASE_PATH"],
        )
        web.mantenimiento.add_maintenance(
            equipment_id=equipment_id,
            fecha=(date.today() - timedelta(days=30)).isoformat(),
            tipo="Preventivo",
            descripcion="Revisión",
            tecnico="Carlos",
            costo="20",
            proximo_mantenimiento=(date.today() - timedelta(days=8)).isoformat(),
            database_path=self.app.config["DATABASE_PATH"],
        )
        laptop_id = web.mantenimiento.add_equipment(
            "Laptop HP",
            database_path=self.app.config["DATABASE_PATH"],
        )
        web.mantenimiento.add_maintenance(
            equipment_id=laptop_id,
            fecha=date.today().isoformat(),
            tipo="Correctivo",
            descripcion="Diagnóstico",
            tecnico="Carlos",
            costo="15",
            proximo_mantenimiento=(date.today() + timedelta(days=7)).isoformat(),
            database_path=self.app.config["DATABASE_PATH"],
        )

        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("notification-count", html)
        self.assertIn("Recordatorio de mantenimiento", html)
        self.assertIn("Laptop HP", html)
        self.assertNotIn("Servidor SRV-01 requiere revisión", html)
        self.assertNotIn("Mantenimiento programado mañana", html)

    def test_profile_name_and_role_are_shown_and_editable(self):
        self._login()
        dashboard = self.client.get("/")
        html = dashboard.get_data(as_text=True)
        self.assertIn("Carlos Gómez", html)
        self.assertIn("Administrador", html)

        users_page = self.client.get("/users")
        token = self._csrf_token(users_page)
        admin_id = self._account_id("test-admin")
        location = web.mantenimiento.list_locations(
            self.app.config["DATABASE_PATH"]
        )[0]
        response = self.client.post(
            f"/users/{admin_id}/update",
            data={
                "csrf_token": token,
                "username": "test-admin",
                "display_name": "Carlos Gómez Jr",
                "sede_id": str(location["id"]),
            },
            follow_redirects=True,
        )
        self.assertIn("Carlos Gómez Jr", response.get_data(as_text=True))
        self.assertIn(
            "Carlos Gómez Jr",
            self.client.get("/").get_data(as_text=True),
        )

    def test_admin_can_create_update_reset_and_deactivate_user(self):
        self._login()
        users_page = self.client.get("/users")
        token = self._csrf_token(users_page)
        locations = web.mantenimiento.list_locations(
            self.app.config["DATABASE_PATH"]
        )
        self.assertIn('name="sede_id" required', users_page.get_data(as_text=True))
        self.assertIn(locations[0]["nombre"], users_page.get_data(as_text=True))
        updated_location = web.mantenimiento.add_location(
            "Sede actualización",
            self.app.config["DATABASE_PATH"],
        )
        updated_locations = web.mantenimiento.list_locations(
            self.app.config["DATABASE_PATH"]
        )
        updated_location = next(
            item for item in updated_locations if item["nombre"] == "Sede actualización"
        )
        response = self.client.post(
            "/users/new",
            data={
                "csrf_token": token,
                "username": "maria",
                "password": "temporary-password",
                "sede_id": str(locations[0]["id"]),
            },
            follow_redirects=True,
        )
        self.assertIn("Cuenta creada correctamente", response.get_data(as_text=True))
        self.assertIn(f"Sede: {locations[0]['nombre']}", response.get_data(as_text=True))
        account_id = self._account_id("maria")

        response = self.client.post(
            f"/users/{account_id}/update",
            data={
                "csrf_token": self._csrf_token(response),
                "username": "maria.p",
                "sede_id": str(updated_location["id"]),
            },
            follow_redirects=True,
        )
        self.assertIn("maria.p", response.get_data(as_text=True))
        self.assertIn("Sede: Sede actualización", response.get_data(as_text=True))

        response = self.client.post(
            f"/users/{account_id}/password",
            data={
                "csrf_token": self._csrf_token(response),
                "password": "new-temporary-password",
            },
            follow_redirects=True,
        )
        self.assertIn("Contraseña actualizada", response.get_data(as_text=True))

        response = self.client.post(
            f"/users/{account_id}/toggle",
            data={"csrf_token": self._csrf_token(response)},
            follow_redirects=True,
        )
        self.assertIn("Cuenta desactivada", response.get_data(as_text=True))

        other_client = self.app.test_client()
        self._login("maria.p", "new-temporary-password", client=other_client)
        self.assertIn("/login", other_client.get("/").headers["Location"])

    def test_user_creation_requires_registered_location(self):
        self._login()
        users_page = self.client.get("/users")
        response = self.client.post(
            "/users/new",
            data={
                "csrf_token": self._csrf_token(users_page),
                "username": "maria",
                "password": "temporary-password",
            },
            follow_redirects=True,
        )

        self.assertIn("La sede es obligatoria.", response.get_data(as_text=True))
        connection = sqlite3.connect(self.app.config["DATABASE_PATH"])
        try:
            user = connection.execute(
                "SELECT 1 FROM usuarios WHERE username = 'maria'"
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(user)

    def test_regular_user_cannot_manage_accounts_but_can_change_password(self):
        self._login()
        response = self.client.get("/users")
        location_id = web.mantenimiento.list_locations(
            self.app.config["DATABASE_PATH"]
        )[0]["id"]
        self.client.post(
            "/users/new",
            data={
                "csrf_token": self._csrf_token(response),
                "username": "maria",
                "password": "temporary-password",
                "sede_id": str(location_id),
            },
        )

        user_client = self.app.test_client()
        self._login("maria", "temporary-password", client=user_client)
        self.assertEqual(user_client.get("/users").status_code, 403)

        password_page = user_client.get("/account/password")
        response = user_client.post(
            "/account/password",
            data={
                "csrf_token": self._csrf_token(password_page),
                "current_password": "temporary-password",
                "password": "my-new-password",
                "confirmation": "my-new-password",
            },
            follow_redirects=True,
        )
        self.assertIn("Tu contraseña se actualizó", response.get_data(as_text=True))
        user_client.post(
            "/logout",
            data={"csrf_token": self._csrf_token(response)},
        )
        self._login("maria", "my-new-password", client=user_client)
        self.assertEqual(user_client.get("/").status_code, 200)

    def test_admin_cannot_deactivate_last_admin(self):
        self._login()
        users_page = self.client.get("/users")
        with self.client.session_transaction() as current_session:
            admin_id = current_session["user_id"]

        response = self.client.post(
            f"/users/{admin_id}/toggle",
            data={"csrf_token": self._csrf_token(users_page)},
            follow_redirects=True,
        )

        self.assertIn("No puedes desactivar tu propia cuenta", response.get_data(as_text=True))
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_short_password_is_rejected_when_creating_user(self):
        self._login()
        users_page = self.client.get("/users")
        response = self.client.post(
            "/users/new",
            data={
                "csrf_token": self._csrf_token(users_page),
                "username": "maria",
                "password": "short",
            },
            follow_redirects=True,
        )

        self.assertIn("al menos 12 caracteres", response.get_data(as_text=True))
        connection = sqlite3.connect(self.app.config["DATABASE_PATH"])
        try:
            user = connection.execute(
                "SELECT 1 FROM usuarios WHERE username = 'maria'"
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNone(user)


if __name__ == "__main__":
    unittest.main()

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import mantenimiento as gestor_pc


class MantenimientoTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        gestor_pc.initialize_database(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_equipment_and_maintenance_history(self):
        equipment_id = gestor_pc.add_equipment(
            "PC recepción", serial="SERIE-001", database_path=self.database_path
        )
        gestor_pc.add_maintenance(
            equipment_id,
            "Preventivo",
            "Limpieza",
            "Ana",
            25,
            database_path=self.database_path,
            estado_final="Reparado",
        )

        equipment = gestor_pc.list_equipment(self.database_path)
        history = gestor_pc.get_maintenance_history(equipment_id, self.database_path)

        self.assertEqual(equipment[0]["nombre"], "PC recepción")
        self.assertEqual(history[0]["tipo"], "Preventivo")
        self.assertEqual(history[0]["costo"], 25)
        self.assertEqual(history[0]["estado_final"], "Reparado")

    def test_existing_database_gets_final_status_column(self):
        legacy_database = Path(self.temp_dir.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_database)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE mantenimientos(
                        id INTEGER PRIMARY KEY,
                        equipo_id INTEGER,
                        fecha TEXT,
                        tipo TEXT,
                        descripcion TEXT,
                        tecnico TEXT,
                        costo REAL,
                        proximo_mantenimiento TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO mantenimientos(
                        id, equipo_id, fecha, tipo, descripcion, tecnico, costo
                    ) VALUES (1, 1, '2026-11-19', 'Preventivo', 'Revisión', 'Ana', 25)
                    """
                )

        gestor_pc.initialize_database(legacy_database)

        with closing(sqlite3.connect(legacy_database)) as connection:
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(mantenimientos)"
                )
            }
            existing_record = connection.execute(
                "SELECT descripcion, estado_final FROM mantenimientos WHERE id = 1"
            ).fetchone()
        self.assertIn("estado_final", columns)
        self.assertEqual(existing_record, ("Revisión", None))

    def test_add_maintenance_rejects_unknown_final_status(self):
        equipment_id = gestor_pc.add_equipment(
            "Equipo A",
            database_path=self.database_path,
        )

        with self.assertRaisesRegex(ValueError, "estado final válido"):
            gestor_pc.add_maintenance(
                equipment_id,
                "Preventivo",
                "",
                "Ana",
                25,
                database_path=self.database_path,
                estado_final="Estado no permitido",
            )

    def test_duplicate_serial_is_reported(self):
        gestor_pc.add_equipment("Equipo A", serial="SERIE-001", database_path=self.database_path)

        with self.assertRaisesRegex(ValueError, "Ya existe"):
            gestor_pc.add_equipment(
                "Equipo B", serial="SERIE-001", database_path=self.database_path
            )

    def test_equipment_with_history_cannot_be_deleted(self):
        equipment_id = gestor_pc.add_equipment("Equipo A", database_path=self.database_path)
        gestor_pc.add_maintenance(
            equipment_id, "Correctivo", "", "", 0, database_path=self.database_path
        )

        with self.assertRaisesRegex(ValueError, "historial"):
            gestor_pc.delete_equipment(equipment_id, self.database_path)

    def test_invalid_cost_is_rejected(self):
        equipment_id = gestor_pc.add_equipment("Equipo A", database_path=self.database_path)

        with self.assertRaisesRegex(ValueError, "número válido"):
            gestor_pc.add_maintenance(
                equipment_id, "Preventivo", "", "", "no es un costo",
                database_path=self.database_path,
            )

    def test_monthly_summary_counts_distinct_equipment_and_maintenance_records(self):
        first_id = gestor_pc.add_equipment("Equipo A", database_path=self.database_path)
        second_id = gestor_pc.add_equipment("Equipo B", database_path=self.database_path)
        for equipment_id, maintenance_date in (
            (first_id, "2025-03-05"),
            (first_id, "2025-03-18"),
            (second_id, "2025-03-22"),
            (second_id, "2025-04-02"),
        ):
            gestor_pc.add_maintenance(
                equipment_id,
                "Preventivo",
                "",
                "",
                0,
                database_path=self.database_path,
                fecha=maintenance_date,
            )

        summary = gestor_pc.get_monthly_summary(2025, 3, self.database_path)

        self.assertEqual(summary["equipos_revisados"], 2)
        self.assertEqual(summary["mantenimientos_registrados"], 3)
        self.assertEqual(len(summary["records"]), 3)

    def test_scheduled_maintenance_is_not_listed_as_completed(self):
        equipment_id = gestor_pc.add_equipment(
            "Equipo programado",
            database_path=self.database_path,
        )
        maintenance_date = date.today().isoformat()
        next_date = (date.today() + timedelta(days=7)).isoformat()
        gestor_pc.add_maintenance(
            equipment_id,
            "Preventivo",
            "",
            "Ana",
            25,
            proximo_mantenimiento=next_date,
            database_path=self.database_path,
            fecha=maintenance_date,
        )

        completed = gestor_pc.list_completed_maintenances(self.database_path)
        history = gestor_pc.get_maintenance_history(
            equipment_id,
            self.database_path,
        )
        summary = gestor_pc.get_monthly_summary(
            date.today().year,
            date.today().month,
            self.database_path,
        )

        self.assertEqual(completed, [])
        self.assertEqual(history, [])
        self.assertEqual(summary["equipos_revisados"], 0)
        self.assertEqual(summary["mantenimientos_registrados"], 0)
        self.assertEqual(summary["records"], [])
        self.assertEqual(len(gestor_pc.list_scheduled_maintenances(self.database_path)), 1)
        self.assertFalse(
            any(
                item["title"].endswith("revisado")
                for item in gestor_pc.get_recent_activity(self.database_path)
            )
        )

    def test_future_maintenance_date_is_allowed(self):
        equipment_id = gestor_pc.add_equipment("Equipo A", database_path=self.database_path)
        future_date = (date.today() + timedelta(days=1)).isoformat()

        gestor_pc.add_maintenance(
            equipment_id,
            "Preventivo",
            "",
            "",
            0,
            database_path=self.database_path,
            fecha=future_date,
        )

        self.assertEqual(
            gestor_pc.list_completed_maintenances(self.database_path)[0]["fecha"],
            future_date,
        )

    def test_future_equipment_registration_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Fecha inválida"):
            gestor_pc.add_equipment(
                "Equipo con fecha futura",
                fecha_registro=(date.today() + timedelta(days=1)).isoformat(),
                database_path=self.database_path,
            )

    def test_overdue_maintenance_is_listed(self):
        equipment_id = gestor_pc.add_equipment("Equipo A", database_path=self.database_path)
        gestor_pc.add_maintenance(
            equipment_id,
            "Preventivo",
            "",
            "",
            0,
            (date.today() - timedelta(days=1)).isoformat(),
            database_path=self.database_path,
        )

        overdue = gestor_pc.get_overdue_maintenance(self.database_path)

        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["nombre"], "Equipo A")

    def test_default_database_uses_local_app_data_directory(self):
        user_data = Path(self.temp_dir.name) / "user-data"

        with patch.dict(os.environ, {"LOCALAPPDATA": str(user_data)}, clear=True):
            database_path = gestor_pc.get_database_path()
            gestor_pc.initialize_database(database_path)

        self.assertTrue(database_path.is_file())
        self.assertEqual(database_path.parent, user_data / "GestorPC")


if __name__ == "__main__":
    unittest.main()

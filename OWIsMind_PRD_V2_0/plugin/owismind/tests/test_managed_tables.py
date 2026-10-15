# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_managed_tables.py
"""storage.migrations.managed_tables - the Admin page's table inventory.

The Admin space answers "which tables does this webapp own, and what are they
called here?". The answer must be exhaustive and self-maintaining: it is derived
from the DDL registry, so a table added to the backend shows up without anyone
remembering to update a list. These tests pin that contract, plus the naming
(project key + optional admin prefix + mandatory namespace) the admin will paste
into a SQL client.

A minimal dataiku stub lets the modules import; nothing here touches a database.
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
sys.path.insert(0, _HERE)

import _dss_stub  # noqa: E402

_dss_stub.install()

from owismind.storage import migrations, sql_config  # noqa: E402


class ManagedTablesTest(unittest.TestCase):
    def test_covers_every_table_the_backend_creates(self):
        """The inventory IS the DDL registry - it cannot silently miss a table."""
        listed = {row["logical"] for row in migrations.managed_tables()}
        self.assertEqual(listed, set(migrations._DDL_BY_LOGICAL))

    def test_every_row_carries_a_role_a_physical_name_and_a_qualified_name(self):
        for row in migrations.managed_tables():
            self.assertTrue(row["role"], row)
            self.assertTrue(row["logical"], row)
            self.assertTrue(row["physical"], row)
            # What an admin pastes into a SQL client: schema + quoted table.
            self.assertEqual(
                row["qualified"], '{}."{}"'.format(sql_config.SCHEMA_NAME, row["physical"])
            )

    def test_physical_names_carry_project_key_and_namespace(self):
        """The naming rule an admin relies on to FIND the table (memory L008)."""
        for row in migrations.managed_tables():
            self.assertTrue(row["physical"].startswith(sql_config.PROJECT_KEY + "_"), row)
            self.assertIn(sql_config.APP_NAMESPACE, row["physical"])
            self.assertTrue(row["physical"].endswith(row["logical"]), row)

    def test_declaration_order_is_preserved(self):
        """Stable order: the admin sees the same list on every reload."""
        self.assertEqual(
            [row["logical"] for row in migrations.managed_tables()],
            list(migrations._DDL_BY_LOGICAL),
        )

    def test_roles_are_unique(self):
        roles = [row["role"] for row in migrations.managed_tables()]
        self.assertEqual(len(roles), len(set(roles)))

    def test_storage_status_exposes_the_inventory_and_the_schema(self):
        status = sql_config.storage_status()
        self.assertEqual(status["schema"], sql_config.SCHEMA_NAME)
        self.assertEqual(
            [row["logical"] for row in status["managed_tables"]],
            [row["logical"] for row in migrations.managed_tables()],
        )
        # The short map the LAB benchmark guide points at stays available.
        self.assertIn("golden_suggestions", status["tables"])


if __name__ == "__main__":
    unittest.main()

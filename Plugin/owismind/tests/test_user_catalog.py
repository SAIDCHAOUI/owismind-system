# Plugin/owismind/tests/test_user_catalog.py
"""agents.user_catalog - user-scoped, impersonated DSS enumeration for the "Demander un
agent" tab (Feedback Hub v1.3). PURE-ish logic tests: dataiku.api_client() and the
impersonated client are faked (no live DSS runtime), so this exercises the impersonation
handshake, the SQL-dataset type/shape filter, the projects/datasets bounds, and the
never-raises contract (impersonation unavailable / listing failure both degrade to
``{"ok": False}``, never an exception escaping to the route).
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

# agents/user_catalog.py imports only ``dataiku`` at module load (no dataiku.sql, no
# pandas): a bare stub module is enough to let the import succeed outside DSS. Each test
# below monkeypatches ``dataiku.api_client`` (or ``_client_as_user`` directly), but the
# attribute must exist upfront so ``setUp`` can save/restore it.
if "dataiku" not in sys.modules:
    sys.modules["dataiku"] = types.ModuleType("dataiku")
if not hasattr(sys.modules["dataiku"], "api_client"):
    sys.modules["dataiku"].api_client = lambda: None

from owismind.agents import user_catalog  # noqa: E402


class _FakeUser:
    def __init__(self, client_as):
        self._client_as = client_as

    def get_client_as(self):
        return self._client_as


class _FakeAdminClient:
    """Stands in for ``dataiku.api_client()``: resolves the browser headers to a login,
    then hands back a per-user fake client via ``get_user(login).get_client_as()``."""

    def __init__(self, login, client_as, auth_info=None, raise_on_auth=None):
        self._login = login
        self._client_as = client_as
        self._auth_info = auth_info
        self._raise_on_auth = raise_on_auth
        self.seen_logins = []

    def get_auth_info_from_browser_headers(self, headers):
        if self._raise_on_auth is not None:
            raise self._raise_on_auth
        if self._auth_info is not None:
            return self._auth_info
        return {"authIdentifier": self._login}

    def get_user(self, login):
        self.seen_logins.append(login)
        return _FakeUser(self._client_as)


class _FakeImpersonatedClient:
    """The user-scoped client returned by ``get_client_as()``."""

    def __init__(self, projects=None, project_keys=None, datasets_by_project=None,
                 raise_list_projects=None, raise_list_datasets=None):
        self._projects = projects
        self._project_keys = project_keys or []
        self._datasets_by_project = datasets_by_project or {}
        self._raise_list_projects = raise_list_projects
        self._raise_list_datasets = raise_list_datasets

    def list_projects(self):
        if self._raise_list_projects is not None:
            raise self._raise_list_projects
        return self._projects

    def list_project_keys(self):
        return self._project_keys

    def get_project(self, key):
        return _FakeProject(key, self._datasets_by_project.get(key, []), self._raise_list_datasets)


class _FakeProject:
    def __init__(self, key, datasets, raise_list_datasets=None):
        self._key = key
        self._datasets = datasets
        self._raise_list_datasets = raise_list_datasets

    def list_datasets(self):
        if self._raise_list_datasets is not None:
            raise self._raise_list_datasets
        return self._datasets


class ClientAsUserTests(unittest.TestCase):
    def setUp(self):
        self._orig_api_client = user_catalog.dataiku.api_client

    def tearDown(self):
        user_catalog.dataiku.api_client = self._orig_api_client

    def test_resolves_login_then_impersonates(self):
        sentinel = object()
        admin = _FakeAdminClient("said.chaoui", sentinel)
        user_catalog.dataiku.api_client = lambda: admin
        client = user_catalog._client_as_user({"Cookie": "abc"})
        self.assertIs(client, sentinel)
        self.assertEqual(admin.seen_logins, ["said.chaoui"])

    def test_missing_auth_identifier_raises(self):
        admin = _FakeAdminClient("x", object(), auth_info={})
        user_catalog.dataiku.api_client = lambda: admin
        with self.assertRaises(KeyError):
            user_catalog._client_as_user({})

    def test_auth_lookup_failure_propagates(self):
        admin = _FakeAdminClient("x", object(), raise_on_auth=RuntimeError("no session"))
        user_catalog.dataiku.api_client = lambda: admin
        with self.assertRaises(RuntimeError):
            user_catalog._client_as_user({})


class ListUserProjectsTests(unittest.TestCase):
    def setUp(self):
        self._orig = user_catalog._client_as_user

    def tearDown(self):
        user_catalog._client_as_user = self._orig

    def test_ok_uses_list_projects_label(self):
        impersonated = _FakeImpersonatedClient(projects=[
            {"projectKey": "B_PROJ", "name": "Bravo Project"},
            {"projectKey": "A_PROJ", "name": "Alpha Project"},
        ])
        user_catalog._client_as_user = lambda headers: impersonated
        result = user_catalog.list_user_projects({})
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["projects"],
            [{"key": "A_PROJ", "label": "Alpha Project"}, {"key": "B_PROJ", "label": "Bravo Project"}],
        )

    def test_missing_label_falls_back_to_key(self):
        impersonated = _FakeImpersonatedClient(projects=[{"projectKey": "P1", "name": None}])
        user_catalog._client_as_user = lambda headers: impersonated
        result = user_catalog.list_user_projects({})
        self.assertEqual(result["projects"], [{"key": "P1", "label": "P1"}])

    def test_list_projects_unavailable_falls_back_to_keys(self):
        impersonated = _FakeImpersonatedClient(
            raise_list_projects=RuntimeError("not permitted"),
            project_keys=["Z_PROJ", "A_PROJ"],
        )
        user_catalog._client_as_user = lambda headers: impersonated
        result = user_catalog.list_user_projects({})
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["projects"],
            [{"key": "A_PROJ", "label": "A_PROJ"}, {"key": "Z_PROJ", "label": "Z_PROJ"}],
        )

    def test_impersonation_unavailable_degrades_gracefully(self):
        def _boom(headers):
            raise RuntimeError("Impersonation in webapps not granted")

        user_catalog._client_as_user = _boom
        result = user_catalog.list_user_projects({})
        self.assertEqual(result, {"ok": False, "reason": "impersonation_unavailable"})

    def test_listing_failure_never_raises(self):
        impersonated = _FakeImpersonatedClient(
            raise_list_projects=RuntimeError("boom"),
        )
        # list_project_keys() is not defined on this fake (AttributeError on fallback).
        impersonated.list_project_keys = None
        user_catalog._client_as_user = lambda headers: impersonated
        result = user_catalog.list_user_projects({})
        self.assertEqual(result, {"ok": False, "reason": "listing_failed"})

    def test_projects_are_bounded(self):
        many = [{"projectKey": "P{:04d}".format(i), "name": "P{:04d}".format(i)}
                for i in range(user_catalog.MAX_PROJECTS + 50)]
        impersonated = _FakeImpersonatedClient(projects=many)
        user_catalog._client_as_user = lambda headers: impersonated
        result = user_catalog.list_user_projects({})
        self.assertEqual(len(result["projects"]), user_catalog.MAX_PROJECTS)


class ListUserSqlDatasetsTests(unittest.TestCase):
    def setUp(self):
        self._orig = user_catalog._client_as_user

    def tearDown(self):
        user_catalog._client_as_user = self._orig

    def test_invalid_project_key_short_circuits_before_impersonation(self):
        def _boom(headers):
            self.fail("_client_as_user should not be called for an invalid project_key")

        user_catalog._client_as_user = _boom
        result = user_catalog.list_user_sql_datasets({}, "")
        self.assertEqual(result, {"ok": False, "reason": "invalid_project_key"})
        result_none = user_catalog.list_user_sql_datasets({}, None)
        self.assertEqual(result_none, {"ok": False, "reason": "invalid_project_key"})

    def test_filters_to_sql_datasets_only(self):
        datasets = [
            {"name": "revenues", "type": "PostgreSQL",
             "params": {"connection": "SQL_owi", "table": "revenues_tbl"}},
            {"name": "raw_files", "type": "Filesystem", "params": {}},
            {"name": "custom_conn", "type": "SomeExoticConnector",
             "params": {"connection": "conn2", "table": "tbl2"}},
            {"name": "no_table_no_conn", "type": "SomeExoticConnector", "params": {}},
        ]
        impersonated = _FakeImpersonatedClient(datasets_by_project={"PROJ": datasets})
        user_catalog._client_as_user = lambda headers: impersonated
        result = user_catalog.list_user_sql_datasets({}, "PROJ")
        self.assertTrue(result["ok"])
        names = [d["dataset"] for d in result["datasets"]]
        # PostgreSQL (whitelisted type) and custom_conn (has connection+table shape) kept;
        # raw_files (non-SQL type, no shape) and no_table_no_conn (neither) excluded.
        self.assertEqual(sorted(names), ["custom_conn", "revenues"])

    def test_dataset_fields_shape(self):
        datasets = [{"name": "revenues", "type": "PostgreSQL",
                     "params": {"connection": "SQL_owi", "table": "revenues_tbl"}}]
        impersonated = _FakeImpersonatedClient(datasets_by_project={"PROJ": datasets})
        user_catalog._client_as_user = lambda headers: impersonated
        result = user_catalog.list_user_sql_datasets({}, "PROJ")
        self.assertEqual(result["datasets"], [{
            "dataset": "revenues", "table": "revenues_tbl",
            "connection": "SQL_owi", "type": "PostgreSQL",
        }])

    def test_impersonation_unavailable_degrades_gracefully(self):
        def _boom(headers):
            raise RuntimeError("no permission")

        user_catalog._client_as_user = _boom
        result = user_catalog.list_user_sql_datasets({}, "PROJ")
        self.assertEqual(result, {"ok": False, "reason": "impersonation_unavailable"})

    def test_listing_failure_never_raises(self):
        impersonated = _FakeImpersonatedClient(
            datasets_by_project={}, raise_list_datasets=RuntimeError("boom")
        )
        user_catalog._client_as_user = lambda headers: impersonated
        result = user_catalog.list_user_sql_datasets({}, "PROJ")
        self.assertEqual(result, {"ok": False, "reason": "listing_failed"})

    def test_datasets_are_bounded(self):
        many = [
            {"name": "ds{}".format(i), "type": "PostgreSQL",
             "params": {"connection": "c", "table": "t{}".format(i)}}
            for i in range(user_catalog.MAX_DATASETS + 20)
        ]
        impersonated = _FakeImpersonatedClient(datasets_by_project={"PROJ": many})
        user_catalog._client_as_user = lambda headers: impersonated
        result = user_catalog.list_user_sql_datasets({}, "PROJ")
        self.assertEqual(len(result["datasets"]), user_catalog.MAX_DATASETS)


if __name__ == "__main__":
    unittest.main()

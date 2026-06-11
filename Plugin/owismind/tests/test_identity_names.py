# Plugin/owismind/tests/test_identity_names.py
"""derive_full_name: DSS logins are 'prenom.nom' org-wide -> 'Prenom Nom'."""
import os, sys, types, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

# identity.py imports ``dataiku`` at module load for the auth lookup, which is not
# available outside the DSS runtime. derive_full_name is a PURE function that never
# touches dataiku, so we inject a minimal stub module just to let the import succeed
# (no install — the README documents this "(or a stub)" approach for dataiku-coupled modules).
if "dataiku" not in sys.modules:
    sys.modules["dataiku"] = types.ModuleType("dataiku")

from owismind.security.identity import derive_full_name  # noqa: E402


class FullNameTests(unittest.TestCase):
    def test_prenom_nom(self):
        self.assertEqual(derive_full_name("said.chaoui"), "Said Chaoui")

    def test_hyphenated_first_name(self):
        self.assertEqual(derive_full_name("jean-marc.dupont"), "Jean-Marc Dupont")

    def test_no_dot_falls_back_to_titlecased_login(self):
        self.assertEqual(derive_full_name("admin"), "Admin")

    def test_multi_dot_keeps_all_segments(self):
        self.assertEqual(derive_full_name("marie.claire.bernard"), "Marie Claire Bernard")

    def test_empty(self):
        self.assertIsNone(derive_full_name(""))
        self.assertIsNone(derive_full_name(None))

if __name__ == "__main__":
    unittest.main()

"""Anti-drift guard for the Flow recipe mirror (audit 2026-08-05, AG-02).

flow/README.md documents the invariant "the two copies of each template recipe
are byte-identical; do not fix them per zone", but until now nothing enforced
it: a correction applied to the revenue zone alone would leave the tickets zone
on older code, silently. This test turns the documented invariant into a
failing build the moment the pairs diverge. The canonical copy is the revenue
zone one (flow_builder clones its payload for new domains).
"""

import filecmp
import os
import unittest

_FLOW = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "flow")

_REVENUE_ZONE = "SalesDrive_Revenue_Expert_zone/python-recipes"
_TICKETS_ZONE = "CSC_ticket_AI_Agent_zone/python-recipes"

_PAIRS = [
    ("compute_DRIVE_Revenues_profile.py",
     "compute_TroubleTickets_year_profile.py"),
    ("compute_DRIVE_Revenues_value_index.py",
     "compute_TroubleTickets_year_value_index.py"),
    ("compute_DRIVE_Revenues_Value_Catalog.py",
     "compute_TroubleTickets_year_value_catalogue.py"),
]


class TestFlowRecipeMirror(unittest.TestCase):
    def test_zone_copies_are_byte_identical(self):
        for revenue_name, tickets_name in _PAIRS:
            revenue = os.path.join(_FLOW, _REVENUE_ZONE, revenue_name)
            tickets = os.path.join(_FLOW, _TICKETS_ZONE, tickets_name)
            self.assertTrue(os.path.isfile(revenue), "missing %s" % revenue)
            self.assertTrue(os.path.isfile(tickets), "missing %s" % tickets)
            self.assertTrue(
                filecmp.cmp(revenue, tickets, shallow=False),
                "Zone recipe copies diverged: %s vs %s. Per flow/README.md the "
                "copies must stay byte-identical: apply the change to BOTH "
                "files (the revenue zone copy is the canonical one)."
                % (revenue_name, tickets_name))


if __name__ == "__main__":
    unittest.main()

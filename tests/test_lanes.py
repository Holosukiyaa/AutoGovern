from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ag.catalog import get, list_lane
from ag.gui import TOOLS as GUI_TOOLS
from ag.lanes import LANES, strategy_fields, tools
from ag.mcp import TOOLS


class LaneTests(unittest.TestCase):
    def test_only_ship_may_set_product_or_refuse_finish(self) -> None:
        ids = [lane.ID for lane in LANES]
        self.assertEqual(["ship", "heal", "lift", "see"], ids)
        for lane in LANES:
            if lane.ID == "ship":
                self.assertTrue(lane.SETS_PRODUCT)
                self.assertTrue(lane.MAY_REFUSE_FINISH)
                self.assertTrue(lane.TOOLS)
            else:
                self.assertFalse(lane.SETS_PRODUCT)
                self.assertFalse(lane.MAY_REFUSE_FINISH)

    def test_mcp_tools_lanes_then_gui(self) -> None:
        lane_names = [str(item["name"]) for item in tools()]
        self.assertEqual(
            [
                "ag_status",
                "ag_enroll",
                "ag_start",
                "ag_verify",
                "ag_finish",
                "ag_abandon",
                "ag_unenroll",
                "ag_usage",
            ],
            lane_names,
        )
        self.assertNotIn("ag_gui", lane_names)
        self.assertEqual(["ag_gui"], [str(item["name"]) for item in GUI_TOOLS])
        self.assertEqual(lane_names + ["ag_gui"], [str(item["name"]) for item in TOOLS])

    def test_strategies_are_numbered_per_lane(self) -> None:
        ship = list_lane("ship")
        self.assertEqual(11, len(ship))
        self.assertEqual(list(range(1, 12)), [item["seq"] for item in ship])
        self.assertEqual("ship-9", get("ship", 9)["code"])
        self.assertIn("金丝雀", get("ship", 9)["name"])
        self.assertTrue(get("ship", 10)["pluggable"])
        self.assertFalse(get("ship", 2)["pluggable"])
        for lane in ("heal", "lift", "see"):
            items = list_lane(lane)
            self.assertGreaterEqual(len(items), 3, lane)
            self.assertEqual(list(range(1, len(items) + 1)), [item["seq"] for item in items])
            for item in items:
                self.assertTrue(item["story"])
                self.assertTrue(item["how"])
                self.assertTrue(item["solves"])
                fields = strategy_fields(item, default_pluggable=True)
                self.assertTrue(fields["pluggable"], item["code"])
                self.assertEqual("usage", fields["probe"])
                self.assertFalse(fields["in_product_tree"])


if __name__ == "__main__":
    unittest.main()

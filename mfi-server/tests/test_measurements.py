"""Tests for mfi_server.measurements: alarm flattening, energy counter, latest values."""
from __future__ import annotations

import unittest

from mfi_server.measurements import EnergyCounter, Measurements, flatten_alarm

MAC = "02aabbccdd01"
OTHER_MAC = "02aabbccdd02"


class TestFlattenAlarm(unittest.TestCase):
    def test_entries_inherit_parent_fields(self):
        alarm = [
            {"sId": "s1", "time": 0, "entries": [{"tag": "v_rms", "val": 230.1}, {"tag": "pf", "val": 0.9}]},
            {"sId": "s2", "tag": "output", "val": 1},
        ]
        self.assertEqual(
            flatten_alarm(alarm),
            [
                {"sId": "s1", "time": 0, "tag": "v_rms", "val": 230.1},
                {"sId": "s1", "time": 0, "tag": "pf", "val": 0.9},
                {"sId": "s2", "tag": "output", "val": 1},
            ],
        )

    def test_not_a_list_gives_empty(self):
        self.assertEqual(flatten_alarm(None), [])
        self.assertEqual(flatten_alarm(["x"]), [])

    def test_empty_list_gives_empty(self):
        self.assertEqual(flatten_alarm([]), [])

    def test_entry_overrides_parent_field(self):
        alarm = [{"sId": "s1", "tag": "old", "entries": [{"tag": "pf", "val": 0.9}]}]
        self.assertEqual(flatten_alarm(alarm), [{"sId": "s1", "tag": "pf", "val": 0.9}])

    def test_parent_without_entries_is_copied(self):
        item = {"sId": "s2", "tag": "output", "val": 1}
        out = flatten_alarm([item])
        self.assertEqual(out, [{"sId": "s2", "tag": "output", "val": 1}])
        self.assertIsNot(out[0], item)
        out[0]["val"] = 0
        self.assertEqual(item["val"], 1)

    def test_empty_entries_emit_parent_without_entries(self):
        self.assertEqual(flatten_alarm([{"sId": "s3", "time": 5, "entries": []}]), [{"sId": "s3", "time": 5}])

    def test_input_is_not_changed(self):
        item = {"sId": "s1", "entries": [{"tag": "pf", "val": 0.9}]}
        flatten_alarm([item])
        self.assertIn("entries", item)

    def test_non_dict_items_and_entries_are_skipped(self):
        alarm = [1, None, {"sId": "s4", "entries": [7, {"tag": "pf", "val": 0.8}]}]
        self.assertEqual(flatten_alarm(alarm), [{"sId": "s4", "tag": "pf", "val": 0.8}])


class TestEnergyCounter(unittest.TestCase):
    def test_first_value_is_returned(self):
        self.assertEqual(EnergyCounter().update("s1", 1000.0, 0), 1000.0)

    def test_reset_adds_previous_value(self):
        counter = EnergyCounter()
        counter.update("s1", 1000.0, 0)
        self.assertEqual(counter.update("s1", 10.0, 1000), 1010.0)

    def test_small_rise_kept_and_jump_discarded(self):
        counter = EnergyCounter()
        self.assertEqual(counter.update("s2", 100.0, 0), 100.0)
        self.assertEqual(counter.update("s2", 100.5, 1000), 100.5)
        self.assertEqual(counter.update("s2", 500.0, 2000), 100.5)
        self.assertEqual(counter.update("s2", 101.0, 3000), 101.0)

    def test_jump_discarded_after_reset(self):
        # 10 Wh in 1000 ms is 0.01 Wh/ms, above MAX_WH_PER_MS, so the 20 Wh
        # reading is discarded and the total stays at 1010.0 (base 1000 + last 10).
        counter = EnergyCounter()
        counter.update("s1", 1000.0, 0)
        self.assertEqual(counter.update("s1", 10.0, 1000), 1010.0)
        self.assertEqual(counter.update("s1", 20.0, 2000), 1010.0)

    def test_equal_value_is_saved(self):
        counter = EnergyCounter()
        counter.update("s4", 50.0, 0)
        self.assertEqual(counter.update("s4", 50.0, 1000), 50.0)

    def test_rise_with_non_increasing_time_is_discarded(self):
        counter = EnergyCounter()
        self.assertEqual(counter.update("s3", 100.0, 1000), 100.0)
        self.assertEqual(counter.update("s3", 101.0, 1000), 100.0)

    def test_sensors_are_independent(self):
        counter = EnergyCounter()
        self.assertEqual(counter.update("s6", 1000.0, 0), 1000.0)
        self.assertEqual(counter.update("s7", 5.0, 0), 5.0)
        self.assertEqual(counter.update("s6", 1000.5, 1000), 1000.5)


class TestMeasurements(unittest.TestCase):
    def test_ingest_keeps_known_tags(self):
        m = Measurements()
        payload = {
            "alarm": [
                {
                    "sId": "s1",
                    "time": 0,
                    "entries": [
                        {"tag": "output", "val": 1},
                        {"tag": "active_pwr", "val": 12.5},
                        {"tag": "energy_sum", "val": 1000},
                    ],
                }
            ]
        }
        m.ingest(MAC, payload, 5000)
        self.assertEqual(m.latest(MAC), {"s1": {"output": 1, "active_pwr": 12.5, "energy_sum": 1000.0}})

    def test_energy_sum_is_compensated_after_reset(self):
        m = Measurements()
        m.ingest(MAC, {"alarm": [{"sId": "s1", "tag": "energy_sum", "val": 1000}]}, 5000)
        m.ingest(MAC, {"alarm": [{"sId": "s1", "tag": "energy_sum", "val": 10}]}, 6000)
        self.assertEqual(m.latest(MAC)["s1"]["energy_sum"], 1010.0)

    def test_unknown_tag_is_ignored(self):
        m = Measurements()
        m.ingest(MAC, {"alarm": [{"sId": "s1", "tag": "unknown_tag", "val": 3}]}, 5000)
        self.assertEqual(m.latest(MAC), {})

    def test_unknown_mac_is_empty(self):
        m = Measurements()
        m.ingest(MAC, {"alarm": [{"sId": "s1", "tag": "pf", "val": 0.9}]}, 5000)
        self.assertEqual(m.latest("02aabbccdd09"), {})

    def test_bool_and_text_values_are_ignored(self):
        m = Measurements()
        alarm = [{"sId": "s1", "tag": "output", "val": True}, {"sId": "s1", "tag": "pf", "val": "0.9"}]
        m.ingest(MAC, {"alarm": alarm}, 5000)
        self.assertEqual(m.latest(MAC), {})

    def test_sensor_id_must_be_string(self):
        m = Measurements()
        m.ingest(MAC, {"alarm": [{"sId": 5, "tag": "pf", "val": 0.9}]}, 5000)
        self.assertEqual(m.latest(MAC), {})

    def test_energy_with_text_time_is_ignored(self):
        m = Measurements()
        m.ingest(MAC, {"alarm": [{"sId": "s1", "tag": "energy_sum", "val": 10, "time": "soon"}]}, 5000)
        self.assertEqual(m.latest(MAC), {})

    def test_payload_without_alarm_stores_nothing(self):
        m = Measurements()
        m.ingest(MAC, {}, 5000)
        self.assertEqual(m.latest(MAC), {})

    def test_later_value_replaces_earlier(self):
        m = Measurements()
        m.ingest(MAC, {"alarm": [{"sId": "s1", "tag": "pf", "val": 0.9}]}, 5000)
        m.ingest(MAC, {"alarm": [{"sId": "s1", "tag": "pf", "val": 0.8}]}, 6000)
        self.assertEqual(m.latest(MAC), {"s1": {"pf": 0.8}})

    def test_devices_are_separate(self):
        m = Measurements()
        m.ingest(MAC, {"alarm": [{"sId": "s1", "tag": "pf", "val": 0.9}]}, 5000)
        m.ingest(OTHER_MAC, {"alarm": [{"sId": "s1", "tag": "pf", "val": 0.5}]}, 5000)
        self.assertEqual(m.latest(MAC), {"s1": {"pf": 0.9}})
        self.assertEqual(m.latest(OTHER_MAC), {"s1": {"pf": 0.5}})

    def test_latest_returns_a_copy(self):
        m = Measurements()
        m.ingest(MAC, {"alarm": [{"sId": "s1", "tag": "pf", "val": 0.9}]}, 5000)
        copied = m.latest(MAC)
        copied["s1"]["pf"] = 0
        self.assertEqual(m.latest(MAC)["s1"]["pf"], 0.9)


if __name__ == "__main__":
    unittest.main()

"""EPIC-04 checks for mfi_server_next.sensors (standard library only, offline)."""
import unittest

from mfi_server_next import sensors

MPOWER_CASES = [("P1U", 1), ("P1E", 1), ("P3U", 3), ("P3E", 3), ("P8U", 8), ("P6E", 6)]


class TestOutletCounts(unittest.TestCase):
    def test_mpower_outlets(self):
        self.assertEqual(
            sensors.MPOWER_OUTLETS,
            {"P1U": 1, "P1E": 1, "P3U": 3, "P3E": 3, "P8U": 8, "P6E": 6},
        )
        for model, count in MPOWER_CASES:
            with self.subTest(model=model):
                self.assertEqual(sensors.outlet_count(model), count)

    def test_inwall_and_mport_counts(self):
        self.assertEqual(sensors.outlet_count("IWO2U"), 2)
        self.assertEqual(sensors.outlet_count("IWD1U"), 1)
        self.assertEqual(sensors.outlet_count("IWS1U"), 0)
        self.assertEqual(sensors.outlet_count("M2M"), 0)
        self.assertEqual(sensors.port_count("IWS1U"), 0)
        self.assertEqual(sensors.port_count("M2M"), 3)
        self.assertEqual(sensors.port_count("M2S"), 1)

    def test_unknown_model_raises(self):
        with self.assertRaises(ValueError):
            sensors.outlet_count("NOPE")
        with self.assertRaises(ValueError):
            sensors.port_count("NOPE")


class TestBuildPortConfig(unittest.TestCase):
    def test_mport_has_three_ports(self):
        res = sensors.build_port_config({"mac": "002722000001", "model": "M2M"})
        self.assertEqual(res["_type"], "setparam")
        pc = res["mgmt"]["port_cfg"]
        self.assertIn("port.1", pc)
        self.assertIn("port.3", pc)
        self.assertNotIn("port.4", pc)
        self.assertEqual(pc, "port.1.mode=off\nport.2.mode=off\nport.3.mode=off")

    def test_mport_sensor_lines(self):
        res = sensors.build_port_config(
            {"mac": "002722000001", "model": "M2M", "sensor": {"port": 1, "model": "MSW", "label": "Motion"}}
        )
        self.assertEqual(
            res["mgmt"]["port_cfg"],
            "port.1.model=MSW\nport.1.label=Motion\nport.1.sensorId=1\nport.2.mode=off\nport.3.mode=off",
        )

    def test_mport_port_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            sensors.build_port_config(
                {"mac": "002722000001", "model": "M2M", "sensor": {"port": 4, "model": "MSW", "label": "x"}}
            )

    def test_mport_port_zero_raises(self):
        with self.assertRaises(ValueError):
            sensors.build_port_config(
                {"mac": "002722000001", "model": "M2M", "sensor": {"port": 0, "model": "MSW", "label": "x"}}
            )

    def test_mport_label_with_line_break_is_rejected(self):
        with self.assertRaises(ValueError):
            sensors.build_port_config(
                {"mac": "002722000001", "model": "M2M",
                 "sensor": {"port": 1, "model": "MSW", "label": "x\nport.2.mode=on"}}
            )

    def test_mport_model_with_line_break_is_rejected(self):
        with self.assertRaises(ValueError):
            sensors.build_port_config(
                {"mac": "002722000001", "model": "M2M",
                 "sensor": {"port": 1, "model": "MS\nW", "label": "ok"}}
            )

    def test_mport_non_integer_port_is_rejected(self):
        for port in ("1", None, True):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    sensors.build_port_config(
                        {"mac": "002722000001", "model": "M2M",
                         "sensor": {"port": port, "model": "MSW", "label": "x"}}
                    )

    def test_mport_non_string_sensor_model_is_rejected(self):
        with self.assertRaises(ValueError):
            sensors.build_port_config(
                {"mac": "002722000001", "model": "M2M",
                 "sensor": {"port": 1, "model": 5, "label": "x"}}
            )

    def test_unknown_model_raises(self):
        with self.assertRaises(ValueError):
            sensors.build_port_config({"model": "NOPE"})

    def test_no_request_returns_setparam_without_raising(self):
        for request in (None, "text", {}):
            with self.subTest(request=request):
                res = sensors.build_port_config(request)
                self.assertEqual(res, {"_type": "setparam", "mgmt": {"port_cfg": ""}})

    def test_no_argument_has_dict_mgmt_and_str_type(self):
        res = sensors.build_port_config()
        self.assertIsInstance(res["mgmt"], dict)
        self.assertIsInstance(res["_type"], str)


class TestDeviceConfigAndInWall(unittest.TestCase):
    def test_dimmer_defaults_to_switch(self):
        self.assertEqual(sensors.device_cfg("IWD1U")["dimmer_mode"], "switch")
        self.assertEqual(sensors.build_port_config({"model": "IWD1U"})["mgmt"]["device_cfg"], "dimmer_mode=switch")

    def test_outlet_model_has_no_device_cfg(self):
        self.assertEqual(sensors.device_cfg("P3U"), {})

    def test_inwall_switch_has_no_outputs(self):
        self.assertEqual(sensors.outlet_count("IWS1U"), 0)
        self.assertNotIn("vpower.1", sensors.build_port_config({"model": "IWS1U"})["mgmt"]["port_cfg"])

    def test_inwall_outlet_has_two_outputs(self):
        pc = sensors.build_port_config({"model": "IWO2U"})["mgmt"]["port_cfg"]
        self.assertEqual(pc, "vpower.1.output=0\nvpower.1.lock=0\nvpower.2.output=0\nvpower.2.lock=0")


class TestParseMeasurements(unittest.TestCase):
    def test_entries_are_flattened_with_parent_fields(self):
        alarm = [
            {
                "sId": 7,
                "type": "output",
                "time": 1000,
                "model": "Outlet",
                "entries": [
                    {"tag": "active_pwr", "val": 12.5},
                    {"tag": "v_rms", "val": 230},
                ],
            }
        ]
        r = sensors.parse_measurements(alarm)
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0]["sId"], 7)
        self.assertEqual(r[0]["type"], "output")
        self.assertEqual(r[0]["time"], 1000)
        self.assertEqual(r[0]["tag"], "active_pwr")
        self.assertEqual(r[0]["val"], 12.5)
        self.assertEqual(r[1]["tag"], "v_rms")
        self.assertEqual(r[1]["val"], 230)
        self.assertNotIn("entries", r[0])
        self.assertEqual(sensors.parse_measurements(None), [])

    def test_item_without_entries_is_copied(self):
        r = sensors.parse_measurements([{"sId": 3, "type": "input", "time": 0, "val": 1}])
        self.assertEqual(r, [{"sId": 3, "type": "input", "time": 0, "val": 1}])


class TestSensorRegistry(unittest.TestCase):
    def test_add_unlinks_sensor_on_same_port(self):
        reg = sensors.SensorRegistry()
        s = reg.add("002722000001", 1, "MSW", "Motion")
        self.assertEqual(s["calibration"], "xyz")
        old = s["sId"]
        s2 = reg.add("002722000001", 1, "DS", "Door")
        self.assertIsNone(reg.get(old))
        self.assertEqual(len(reg.list()), 1)
        self.assertEqual(reg.get(s2["sId"])["label"], "Door")

    def test_move_keeps_sid_label_and_calibration(self):
        reg = sensors.SensorRegistry()
        reg.add("002722000001", 1, "MSW", "Motion")
        s2 = reg.add("002722000001", 1, "DS", "Door")
        moved = reg.move(s2["sId"], "002722000002", 2)
        self.assertEqual(moved["sId"], s2["sId"])
        self.assertEqual(moved["mac"], "002722000002")
        self.assertEqual(moved["port"], 2)
        self.assertEqual(moved["label"], "Door")
        self.assertEqual(moved["calibration"], "xyz")
        with self.assertRaises(ValueError):
            reg.move(999999, "002722000002", 3)

    def test_move_onto_occupied_port_unlinks_it(self):
        reg = sensors.SensorRegistry()
        a = reg.add("002722000001", 1, "MSW", "A")
        b = reg.add("002722000002", 1, "DS", "B")
        moved = reg.move(b["sId"], "002722000001", 1)
        self.assertIsNone(reg.get(a["sId"]))
        self.assertEqual(moved["mac"], "002722000001")
        self.assertEqual(len(reg.list()), 1)

    def test_get_returns_a_copy(self):
        reg = sensors.SensorRegistry()
        s = reg.add("002722000001", 1, "MSW", "Motion")
        copied = reg.get(s["sId"])
        copied["label"] = "changed"
        self.assertEqual(reg.get(s["sId"])["label"], "Motion")

    def test_set_calibration(self):
        reg = sensors.SensorRegistry()
        s = reg.add("002722000001", 1, "CS", "Current")
        self.assertEqual(reg.set_calibration(s["sId"], "abc")["calibration"], "abc")
        self.assertEqual(reg.get(s["sId"])["calibration"], "abc")
        with self.assertRaises(ValueError):
            reg.set_calibration(999999)

    def test_remove(self):
        reg = sensors.SensorRegistry()
        s = reg.add("002722000001", 1, "MSW", "Motion")
        reg.remove(s["sId"])
        self.assertIsNone(reg.get(s["sId"]))
        self.assertEqual(reg.list(), [])

    def test_add_rejects_non_integer_port_and_non_string_mac(self):
        reg = sensors.SensorRegistry()
        with self.assertRaises(ValueError):
            reg.add("002722000001", "1", "MSW")
        with self.assertRaises(ValueError):
            reg.add(123, 1, "MSW")

    def test_add_rejects_label_with_line_break(self):
        reg = sensors.SensorRegistry()
        with self.assertRaises(ValueError):
            reg.add("002722000001", 1, "MSW", "a\nb")

    def test_set_calibration_rejects_line_break(self):
        reg = sensors.SensorRegistry()
        s = reg.add("002722000001", 1, "CS", "Current")
        with self.assertRaises(ValueError):
            reg.set_calibration(s["sId"], "x\ny")

    def test_remove_unknown_sid_is_ignored(self):
        reg = sensors.SensorRegistry()
        reg.remove(999999)
        self.assertEqual(reg.list(), [])

    def test_add_rejects_malformed_mac(self):
        reg = sensors.SensorRegistry()
        for mac in ("", "zz", "00272200000A", "0027220000", "002722-00001"):
            with self.subTest(mac=mac):
                with self.assertRaises(ValueError):
                    reg.add(mac, 1, "MSW")

    def test_add_rejects_non_positive_port(self):
        reg = sensors.SensorRegistry()
        for port in (0, -5):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    reg.add("002722000001", port, "MSW")

    def test_add_rejects_model_with_line_break(self):
        reg = sensors.SensorRegistry()
        with self.assertRaises(ValueError):
            reg.add("002722000001", 1, "X\nport.1.mode=off")

    def test_move_rejects_malformed_mac_and_bad_port(self):
        reg = sensors.SensorRegistry()
        s = reg.add("002722000001", 1, "MSW")
        with self.assertRaises(ValueError):
            reg.move(s["sId"], "00272200000A", 2)
        with self.assertRaises(ValueError):
            reg.move(s["sId"], "002722000002", 0)


if __name__ == "__main__":
    unittest.main()

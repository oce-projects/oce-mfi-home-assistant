"""Checks of the ser2net configuration and of the serial line reset (EPIC-04, CA5).

Standard library only, offline.
"""
import unittest

from mfi_server_next import serial


def _lines(cfg):
    """The key=value lines of the ser2net configuration of a setparam message."""
    return cfg["mgmt"]["ser2net_cfg"].split("\n")


class TestBuildSer2netCfg(unittest.TestCase):
    def test_m2s_request_gives_setparam_with_mgmt_dict(self):
        cfg = serial.build_ser2net_cfg({
            "model": "M2S",
            "serial": {
                "enable": "on",
                "baudRate": 300,
                "parity": "none",
                "uartMode": "rs232",
                "termination": "off",
                "antenna": "off",
            },
        })
        self.assertEqual(cfg["_type"], "setparam")
        self.assertIsInstance(cfg["mgmt"], dict)
        self.assertIn("ser2net_cfg", cfg["mgmt"])
        self.assertIn("enable=on", _lines(cfg))
        self.assertIn("baudRate=300", _lines(cfg))

    def test_rs485_even_115200_accepted(self):
        cfg = serial.build_ser2net_cfg({"serial": {"baudRate": 115200, "parity": "even", "uartMode": "rs485"}})
        self.assertIn("baudRate=115200", _lines(cfg))
        self.assertIn("parity=even", _lines(cfg))
        self.assertIn("uartMode=rs485", _lines(cfg))

    def test_every_parity_accepted(self):
        for parity in ("none", "odd", "even"):
            with self.subTest(parity=parity):
                cfg = serial.build_ser2net_cfg({"serial": {"baudRate": 9600, "parity": parity}})
                self.assertIn(f"parity={parity}", _lines(cfg))

    def test_listed_baud_rates_accepted(self):
        for baud in (300, 115200):
            with self.subTest(baud=baud):
                cfg = serial.build_ser2net_cfg({"serial": {"baudRate": baud, "parity": "none"}})
                self.assertIn(f"baudRate={baud}", _lines(cfg))

    def test_baud_rate_not_listed_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            serial.build_ser2net_cfg({"serial": {"baudRate": 250, "parity": "none"}})
        self.assertEqual(ctx.exception.args, ("baudRate",))

    def test_invalid_baud_rate_values_rejected(self):
        for value in ("", "9600.0", "abc", 0, None, True, -9600):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as ctx:
                    serial.build_ser2net_cfg({"serial": {"baudRate": value, "parity": "none"}})
                self.assertEqual(ctx.exception.args, ("baudRate",))

    def test_numeric_string_baud_rate_accepted(self):
        cfg = serial.build_ser2net_cfg({"serial": {"baudRate": "9600", "parity": "none"}})
        self.assertIn("baudRate=9600", _lines(cfg))

    def test_parity_mark_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            serial.build_ser2net_cfg({"serial": {"baudRate": 9600, "parity": "mark"}})
        self.assertEqual(ctx.exception.args, ("parity",))

    def test_rs422_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            serial.build_ser2net_cfg({"serial": {"baudRate": 9600, "parity": "none", "uartMode": "rs422"}})
        self.assertEqual(ctx.exception.args, ("uartMode",))

    def test_line_break_in_a_plain_value_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            serial.build_ser2net_cfg({"serial": {"baudRate": 9600, "parity": "none", "antenna": "off\nport.1=x"}})
        self.assertEqual(ctx.exception.args, ("antenna",))

    def test_no_argument_gives_default_settings(self):
        cfg = serial.build_ser2net_cfg()
        self.assertEqual(cfg["_type"], "setparam")
        self.assertIsInstance(cfg["_type"], str)
        self.assertIsInstance(cfg["mgmt"], dict)
        self.assertIn("baudRate=9600", _lines(cfg))
        self.assertIn("uartMode=rs232", _lines(cfg))
        self.assertEqual(cfg, serial.build_ser2net_cfg(None))

    def test_request_without_serial_uses_defaults(self):
        self.assertEqual(serial.build_ser2net_cfg({"model": "M2S"}), serial.build_ser2net_cfg())


class TestKickSerial(unittest.TestCase):
    def test_command_for_device(self):
        cmd = serial.kick_serial("002722000001")
        self.assertEqual(cmd["_type"], "cmd")
        self.assertEqual(cmd["cmd"], "kick-serial")
        self.assertEqual(cmd["mac"], "002722000001")

    def test_no_argument_does_not_raise(self):
        cmd = serial.kick_serial()
        self.assertEqual(cmd["cmd"], "kick-serial")
        self.assertIsNone(cmd["mac"])

    def test_bad_mac_rejected(self):
        for mac in ("00272200000A", "002722-00001", "0027220000", "00272200000g", 2722000001):
            with self.subTest(mac=mac):
                with self.assertRaises(ValueError) as ctx:
                    serial.kick_serial(mac)
                self.assertEqual(ctx.exception.args, ("mac",))


if __name__ == "__main__":
    unittest.main()

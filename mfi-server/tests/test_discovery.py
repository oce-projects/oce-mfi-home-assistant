"""Tests of the Home Assistant discovery messages (discovery.py): mPower and mPort examples, offline."""
from __future__ import annotations

import unittest

from mfi_server.discovery import discovery_messages

MAC = "02aabbccdd01"
DISCOVERY = "homeassistant"
TOPIC = "mfi"
BASE_KEYS = {"unique_id", "name", "state_topic", "availability_topic", "device"}

EXPECTED_SENSORS = {
    "active_pwr": {"device_class": "power", "unit_of_measurement": "W", "state_class": "measurement"},
    "v_rms": {"device_class": "voltage", "unit_of_measurement": "V", "state_class": "measurement"},
    "i_rms": {"device_class": "current", "unit_of_measurement": "A", "state_class": "measurement"},
    "pf": {"device_class": "power_factor", "state_class": "measurement"},
    "energy_sum": {"device_class": "energy", "unit_of_measurement": "Wh", "state_class": "total_increasing"},
}

EXPECTED_NAMES = {
    "active_pwr": "Power",
    "v_rms": "Voltage",
    "i_rms": "Current",
    "pf": "Power Factor",
    "energy_sum": "Energy",
}


def mpower_device() -> dict:
    return {
        "mac": MAC,
        "model": "mPower",
        "name": "Strip",
        "ports": [
            {"port": 1, "label": "Outlet 1"},
            {"port": 2, "label": "Outlet 2"},
            {"port": 3, "label": "Outlet 3"},
        ],
    }


class MPowerDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.messages = discovery_messages(mpower_device(), DISCOVERY, TOPIC)
        self.configs = dict(self.messages)

    def test_three_ports_give_six_messages_each(self):
        self.assertEqual(len(self.messages), 18)
        self.assertEqual(len(self.configs), 18)

    def test_each_port_has_a_switch_for_its_relay(self):
        for port in (1, 2, 3):
            topic = f"{DISCOVERY}/switch/mfi_{MAC}/{port}_output/config"
            config = self.configs[topic]
            self.assertEqual(config["unique_id"], f"mfi_{MAC}_{port}_output")
            self.assertEqual(config["name"], f"Outlet {port} Output")
            self.assertEqual(config["state_topic"], f"{TOPIC}/{MAC}/{port}/output")
            self.assertEqual(config["command_topic"], f"{TOPIC}/{MAC}/{port}/output/set")
            self.assertEqual(config["payload_on"], "ON")
            self.assertEqual(config["payload_off"], "OFF")
            self.assertEqual(config["state_on"], "ON")
            self.assertEqual(config["state_off"], "OFF")

    def test_each_port_has_the_five_power_sensors(self):
        for port in (1, 2, 3):
            for tag, expected in EXPECTED_SENSORS.items():
                topic = f"{DISCOVERY}/sensor/mfi_{MAC}/{port}_{tag}/config"
                config = self.configs[topic]
                self.assertEqual(config["unique_id"], f"mfi_{MAC}_{port}_{tag}")
                self.assertEqual(config["name"], f"Outlet {port} {EXPECTED_NAMES[tag]}")
                self.assertEqual(config["state_topic"], f"{TOPIC}/{MAC}/{port}/{tag}")
                self.assertEqual({key: config[key] for key in expected}, expected)
                self.assertEqual(set(config) - BASE_KEYS, set(expected))

    def test_all_entities_share_one_device(self):
        for config in self.configs.values():
            self.assertEqual(config["device"]["identifiers"], [f"mfi_{MAC}"])
            self.assertEqual(config["device"]["manufacturer"], "Ubiquiti")
            self.assertEqual(config["device"]["model"], "mPower")
            self.assertEqual(config["device"]["name"], "Strip")
            self.assertEqual(config["availability_topic"], f"{TOPIC}/{MAC}/availability")


class MPortDiscoveryTest(unittest.TestCase):
    def test_unknown_tag_becomes_one_plain_sensor(self):
        device = {
            "mac": MAC,
            "model": "mPort",
            "name": "Hub",
            "ports": [{"port": 1, "label": "Sensor", "tags": ["temperature"]}],
        }
        messages = discovery_messages(device, DISCOVERY, TOPIC)
        self.assertEqual(len(messages), 1)
        topic, config = messages[0]
        self.assertEqual(topic, f"{DISCOVERY}/sensor/mfi_{MAC}/1_temperature/config")
        self.assertEqual(config["unique_id"], f"mfi_{MAC}_1_temperature")
        self.assertEqual(config["name"], "Sensor temperature")
        self.assertEqual(config["state_topic"], f"{TOPIC}/{MAC}/1/temperature")
        self.assertNotIn("device_class", config)
        self.assertNotIn("unit_of_measurement", config)
        self.assertNotIn("state_class", config)


class EdgeCasesTest(unittest.TestCase):
    def test_device_without_ports_gives_no_messages(self):
        self.assertEqual(discovery_messages({"mac": MAC}, DISCOVERY, TOPIC), [])
        self.assertEqual(discovery_messages({"mac": MAC, "ports": []}, DISCOVERY, TOPIC), [])

    def test_empty_tags_fall_back_to_the_standard_set(self):
        device = {"mac": MAC, "ports": [{"port": 1, "label": "A", "tags": []}]}
        messages = discovery_messages(device, DISCOVERY, TOPIC)
        self.assertEqual(len(messages), 6)
        self.assertEqual(messages[0][0], f"{DISCOVERY}/switch/mfi_{MAC}/1_output/config")

    def test_missing_label_uses_the_port_number(self):
        device = {"mac": MAC, "ports": [{"port": 2, "tags": ["output"]}]}
        messages = discovery_messages(device, DISCOVERY, TOPIC)
        self.assertEqual(messages[0][1]["name"], "Port 2 Output")

    def test_non_ascii_label_is_kept(self):
        device = {"mac": MAC, "ports": [{"port": 1, "label": "Lampada \u00e0", "tags": ["active_pwr"]}]}
        messages = discovery_messages(device, DISCOVERY, TOPIC)
        self.assertEqual(messages[0][1]["name"], "Lampada \u00e0 Power")

    def test_firmware_becomes_sw_version_only_when_known(self):
        device = mpower_device()
        messages = discovery_messages(device, DISCOVERY, TOPIC)
        self.assertNotIn("sw_version", messages[0][1]["device"])
        device["firmware"] = "2.1.4"
        messages = discovery_messages(device, DISCOVERY, TOPIC)
        self.assertEqual(messages[0][1]["device"]["sw_version"], "2.1.4")

    def test_device_without_name_or_model_uses_mac_and_empty_model(self):
        device = {"mac": MAC, "ports": [{"port": 1, "label": "A", "tags": ["pf"]}]}
        messages = discovery_messages(device, DISCOVERY, TOPIC)
        self.assertEqual(messages[0][1]["device"]["name"], f"mFi {MAC}")
        self.assertEqual(messages[0][1]["device"]["model"], "")


if __name__ == "__main__":
    unittest.main()

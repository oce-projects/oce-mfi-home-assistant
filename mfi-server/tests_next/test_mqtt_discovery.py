"""EPIC-14 checks for mfi_server_next.mqtt_discovery (standard library only, offline)."""
import unittest

from mfi_server_next import mqtt_discovery

FAKE_MAC = "002722000001"
DISCOVERY = "homeassistant"
PREFIX = "mfi"
MAC_TOPIC = f"{PREFIX}/{FAKE_MAC}"
MEASURE_TAGS = ("active_pwr", "pf", "energy_sum", "v_rms", "i_rms")


def device(model, **extra):
    return {"mac": FAKE_MAC, "model": model, **extra}


def discovery(model, sensors=()):
    return mqtt_discovery.discovery_messages(device(model), sensors)


def by_component(messages, component):
    return [(topic, config) for topic, config in messages if topic.split("/")[1] == component]


def config_of(messages, component, object_id):
    return dict(messages)[f"{DISCOVERY}/{component}/mfi_{FAKE_MAC}/{object_id}/config"]


class TestOutlets(unittest.TestCase):
    def test_p3e_has_three_switches(self):
        switches = by_component(discovery("P3E"), "switch")
        self.assertEqual(len(switches), 3)
        for index, (topic, config) in enumerate(switches, start=1):
            with self.subTest(outlet=index):
                self.assertEqual(topic, f"{DISCOVERY}/switch/mfi_{FAKE_MAC}/{index}_output/config")
                self.assertEqual(config["unique_id"], f"mfi_{FAKE_MAC}_{index}_output")
                self.assertEqual(config["command_topic"], f"{MAC_TOPIC}/{index}/output/set")
                self.assertEqual(config["state_topic"], f"{MAC_TOPIC}/{index}/output")
                self.assertEqual(config["availability_topic"], f"{MAC_TOPIC}/availability")
                self.assertEqual((config["payload_on"], config["payload_off"]), ("ON", "OFF"))

    def test_p3e_has_five_measure_sensors_per_outlet(self):
        messages = discovery("P3E")
        self.assertEqual(len(by_component(messages, "sensor")), 15)
        for index in (1, 2, 3):
            for tag in MEASURE_TAGS:
                with self.subTest(outlet=index, tag=tag):
                    config = config_of(messages, "sensor", f"{index}_{tag}")
                    self.assertEqual(config["unique_id"], f"mfi_{FAKE_MAC}_{index}_{tag}")
                    self.assertEqual(config["state_topic"], f"{MAC_TOPIC}/{index}/{tag}")

    def test_p3e_message_count_is_switches_sensors_and_alarm(self):
        self.assertEqual(len(discovery("P3E")), 19)

    def test_measure_sensor_fields(self):
        messages = discovery("P3E")
        power = config_of(messages, "sensor", "1_active_pwr")
        self.assertEqual((power["device_class"], power["unit_of_measurement"]), ("power", "W"))
        pf = config_of(messages, "sensor", "1_pf")
        self.assertEqual(pf["device_class"], "power_factor")
        self.assertNotIn("unit_of_measurement", pf)
        energy = config_of(messages, "sensor", "2_energy_sum")
        self.assertEqual(
            (energy["device_class"], energy["unit_of_measurement"], energy["state_class"]),
            ("energy", "Wh", "total_increasing"),
        )
        voltage = config_of(messages, "sensor", "3_v_rms")
        self.assertEqual((voltage["device_class"], voltage["unit_of_measurement"]), ("voltage", "V"))
        current = config_of(messages, "sensor", "3_i_rms")
        self.assertEqual((current["device_class"], current["unit_of_measurement"]), ("current", "A"))

    def test_device_block_is_shared_by_every_entity(self):
        expected = {
            "identifiers": [f"mfi_{FAKE_MAC}"],
            "manufacturer": "Ubiquiti",
            "model": "P3E",
            "name": f"mFi {FAKE_MAC}",
        }
        for topic, config in discovery("P3E"):
            with self.subTest(topic=topic):
                self.assertEqual(config["device"], expected)

    def test_device_name_is_used(self):
        messages = mqtt_discovery.discovery_messages(device("P1E", name="Lab"))
        self.assertEqual(config_of(messages, "switch", "1_output")["device"]["name"], "Lab")

    def test_p1e_and_iwo2u_outlet_counts(self):
        self.assertEqual(len(by_component(discovery("P1E"), "switch")), 1)
        self.assertEqual(len(by_component(discovery("P1E"), "sensor")), 5)
        self.assertEqual(len(by_component(discovery("IWO2U"), "switch")), 2)
        self.assertEqual(len(by_component(discovery("IWO2U"), "sensor")), 10)

    def test_topics_are_unique(self):
        topics = [topic for topic, _ in discovery("P3E")]
        self.assertEqual(len(topics), len(set(topics)))

    def test_prefixes_are_used(self):
        messages = mqtt_discovery.discovery_messages(device("P1E"), discovery_prefix="ha", topic_prefix="home")
        self.assertTrue(messages)
        for topic, config in messages:
            with self.subTest(topic=topic):
                self.assertTrue(topic.startswith("ha/"))
                self.assertTrue(config["state_topic"].startswith("home/"))
                self.assertTrue(config["availability_topic"].startswith("home/"))

    def test_unknown_or_missing_model_gives_nothing(self):
        for model in ("NOPE", None, 5):
            with self.subTest(model=model):
                self.assertEqual(mqtt_discovery.discovery_messages({"mac": FAKE_MAC, "model": model}), [])


class TestInWallAndSerial(unittest.TestCase):
    def test_iws1u_has_no_entity(self):
        self.assertEqual(discovery("IWS1U"), [])

    def test_iwd1u_has_one_light_and_no_measure_sensor(self):
        messages = discovery("IWD1U")
        lights = by_component(messages, "light")
        self.assertEqual(len(lights), 1)
        config = config_of(messages, "light", "1_output")
        self.assertIs(config["brightness"], True)
        self.assertEqual(config["brightness_scale"], 100)
        self.assertEqual(config["command_topic"], f"{MAC_TOPIC}/1/output/set")
        self.assertEqual(by_component(messages, "switch"), [])
        self.assertEqual(by_component(messages, "sensor"), [])

    def test_iwd1u_has_light_and_alarm_only(self):
        self.assertEqual(len(discovery("IWD1U")), 2)

    def test_mport_serial_without_sensors_has_no_entity(self):
        self.assertEqual(discovery("M2S"), [])
        self.assertEqual(mqtt_discovery.discovery_messages(device("M2S"), None), [])

    def test_mport_serial_ignores_unknown_sensor_model(self):
        self.assertEqual(discovery("M2S", [{"port": 1, "model": "Serial"}]), [])


class TestMport(unittest.TestCase):
    def test_ths_gives_temperature_and_humidity(self):
        messages = discovery("M2M", [{"port": 2, "model": "THS", "label": "Room"}])
        temperature = config_of(messages, "sensor", "2_temperature")
        self.assertEqual(temperature["name"], "Room Temperature")
        self.assertEqual(temperature["device_class"], "temperature")
        self.assertEqual(temperature["unit_of_measurement"], "\u00b0C")
        self.assertEqual(temperature["state_topic"], f"{MAC_TOPIC}/2/temperature")
        humidity = config_of(messages, "sensor", "2_humidity")
        self.assertEqual((humidity["device_class"], humidity["unit_of_measurement"]), ("humidity", "%"))
        self.assertEqual(len(by_component(messages, "sensor")), 2)

    def test_msw_gives_motion_and_tamper_binary_sensors(self):
        messages = discovery("M2M", [{"port": 1, "model": "MSW"}])
        self.assertEqual(config_of(messages, "binary_sensor", "1_motion")["device_class"], "motion")
        self.assertEqual(config_of(messages, "binary_sensor", "1_tamper")["device_class"], "tamper")
        self.assertEqual(len(by_component(messages, "binary_sensor")), 3)

    def test_output_model_gives_switch_with_default_name(self):
        messages = discovery("M2M", [{"port": 3, "model": "Output 24v"}])
        config = config_of(messages, "switch", "3_output")
        self.assertEqual(config["name"], "Port 3 Output")
        self.assertEqual(config["command_topic"], f"{MAC_TOPIC}/3/output/set")
        self.assertEqual(config["state_topic"], f"{MAC_TOPIC}/3/output")

    def test_unknown_sensor_model_is_skipped(self):
        sensors = [{"port": 1, "model": "NOPE"}, {"port": 2, "model": "RTD", "label": "Tank"}]
        messages = discovery("M2M", sensors)
        self.assertEqual(len(by_component(messages, "sensor")), 1)
        self.assertEqual(config_of(messages, "sensor", "2_temperature")["name"], "Tank Temperature")

    def test_bad_sensor_items_are_skipped(self):
        sensors = [
            None,
            "x",
            {"port": True, "model": "THS"},
            {"port": "1", "model": "THS"},
            {"port": 1, "model": ["THS"]},
        ]
        self.assertEqual(discovery("M2M", sensors), [])

    def test_outlet_model_ignores_sensors_list(self):
        messages = discovery("P1E", [{"port": 1, "model": "THS"}])
        self.assertEqual(len(by_component(messages, "sensor")), 5)
        self.assertNotIn(f"{DISCOVERY}/sensor/mfi_{FAKE_MAC}/1_temperature/config", dict(messages))


class TestAlarm(unittest.TestCase):
    def test_alarm_is_problem_binary_sensor(self):
        config = config_of(discovery("P1E"), "binary_sensor", "alarm")
        self.assertEqual(config["device_class"], "problem")
        self.assertEqual(config["unique_id"], f"mfi_{FAKE_MAC}_alarm")
        self.assertEqual(config["state_topic"], f"{MAC_TOPIC}/alarm")


class TestState(unittest.TestCase):
    def test_state_payloads(self):
        values = {1: {"output": True, "active_pwr": 12.5}, 2: {"output": 0, "v_rms": 230}}
        self.assertEqual(
            mqtt_discovery.state_messages(device("P3E"), values),
            [
                (f"{MAC_TOPIC}/1/output", b"ON"),
                (f"{MAC_TOPIC}/1/active_pwr", b"12.5"),
                (f"{MAC_TOPIC}/2/output", b"OFF"),
                (f"{MAC_TOPIC}/2/v_rms", b"230"),
            ],
        )

    def test_output_is_on_or_off_by_truthiness(self):
        for value, payload in (("", b"OFF"), (1, b"ON"), (None, b"OFF")):
            with self.subTest(value=value):
                messages = mqtt_discovery.state_messages(device("P1E"), {1: {"output": value}})
                self.assertEqual(messages, [(f"{MAC_TOPIC}/1/output", payload)])

    def test_zero_of_other_tags_is_text(self):
        messages = mqtt_discovery.state_messages(device("P1E"), {1: {"energy_sum": 0, "pf": 0.0}})
        self.assertEqual(messages, [(f"{MAC_TOPIC}/1/energy_sum", b"0"), (f"{MAC_TOPIC}/1/pf", b"0.0")])

    def test_non_ascii_text_is_utf8(self):
        messages = mqtt_discovery.state_messages(device("P1E"), {1: {"label": "caff\u00e8"}})
        self.assertEqual(messages, [(f"{MAC_TOPIC}/1/label", "caff\u00e8".encode("utf-8"))])

    def test_empty_values_give_nothing(self):
        self.assertEqual(mqtt_discovery.state_messages(device("P1E"), {}), [])
        self.assertEqual(mqtt_discovery.state_messages(device("P1E"), {1: {}}), [])

    def test_topic_prefix_is_used(self):
        messages = mqtt_discovery.state_messages(device("P1E"), {1: {"output": True}}, topic_prefix="home")
        self.assertEqual(messages, [(f"home/{FAKE_MAC}/1/output", b"ON")])

    def test_state_topic_matches_discovery(self):
        state = mqtt_discovery.state_messages(device("P1E"), {1: {"output": True}})
        config = config_of(discovery("P1E"), "switch", "1_output")
        self.assertEqual(state, [(config["state_topic"], b"ON")])


if __name__ == "__main__":
    unittest.main()

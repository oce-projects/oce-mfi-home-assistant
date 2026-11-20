"""EPIC-14 checks for mfi_server_next.mqtt: MQTT 3.1.1 bytes, the output command bridge and the no-broker case.

Standard library only, offline: no broker, no network, a fake client in memory.
"""
import threading
import unittest

from mfi_server_next import mqtt
from mfi_server_next import tasks

FAKE_MAC = "002722000001"
PREFIX = "mfi"
COMMAND_TOPIC = f"{PREFIX}/{FAKE_MAC}/1/output/set"
REMAINING_CASES = [
    (0, b"\x00"),
    (127, b"\x7f"),
    (128, b"\x80\x01"),
    (16383, b"\xff\x7f"),
    (16384, b"\x80\x80\x01"),
    (268435455, b"\xff\xff\xff\x7f"),
]


class FakeClient:
    """In-memory stand-in for MqttClient: records subscriptions and publications, runs on_connect once."""

    def __init__(self):
        self.subscribed = []
        self.published = []
        self.loop_args = None

    def subscribe(self, topics):
        self.subscribed.append(list(topics))

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, retain))

    def loop_forever(self, stop_event, on_connect=None, on_tick=None, tick_interval_s=0.0):
        self.loop_args = (on_tick, tick_interval_s)
        if on_connect is not None:
            on_connect()


def make_bridge(settings=None, devices=(), latest=None, client_factory=None):
    """A bridge with a fresh queue; the settings default to the topic prefix only."""
    return mqtt.MqttBridge(
        settings if settings is not None else {"mqtt_topic_prefix": PREFIX},
        list_devices=lambda: list(devices),
        queue=tasks.TaskQueue(),
        latest=latest,
        client_factory=client_factory,
    )


class ConnectPacketTest(unittest.TestCase):
    def test_connect_carries_clean_session_password_and_username(self):
        packet = mqtt.build_connect("mfi-test", "user-test", "pw-test", 60, "", b"")
        ptype, flags, body, consumed = mqtt.parse_packet(packet)
        self.assertEqual(packet[0], 0x10)
        self.assertEqual(ptype, mqtt.CONNECT)
        self.assertEqual(flags, 0)
        self.assertEqual(body[:7], b"\x00\x04MQTT\x04")
        self.assertEqual(body[7], 0x02 | 0x40 | 0x80)
        self.assertEqual(body[8:10], b"\x00\x3c")
        self.assertEqual(body[10:20], b"\x00\x08mfi-test")
        self.assertEqual(consumed, len(packet))

    def test_connect_without_credentials_has_only_clean_session(self):
        packet = mqtt.build_connect("c", "", "", 0, "", b"")
        _, _, body, _ = mqtt.parse_packet(packet)
        self.assertEqual(body[7], 0x02)

    def test_partial_packet_is_not_parsed(self):
        packet = mqtt.build_connect("mfi-test", "user-test", "pw-test", 60, "", b"")
        self.assertIsNone(mqtt.parse_packet(packet[:-1]))


class PacketBytesTest(unittest.TestCase):
    def test_qos1_retained_publish_bytes(self):
        packet = mqtt.build_publish("a", b"x", qos=1, retain=True, packet_id=7)
        self.assertEqual(packet, b"\x33\x06\x00\x01a\x00\x07x")

    def test_qos0_publish_bytes(self):
        self.assertEqual(mqtt.build_publish("a", b"x"), b"\x30\x04\x00\x01ax")

    def test_qos1_publish_without_packet_id_is_refused(self):
        with self.assertRaises(ValueError):
            mqtt.build_publish("a", b"x", qos=1)

    def test_subscribe_bytes(self):
        self.assertEqual(mqtt.build_subscribe(1, ["a"]), b"\x82\x06\x00\x01\x00\x01a\x00")

    def test_subscribe_without_topics_is_refused(self):
        with self.assertRaises(ValueError):
            mqtt.build_subscribe(1, [])

    def test_pingreq_and_disconnect_bytes(self):
        self.assertEqual(mqtt.build_pingreq(), b"\xc0\x00")
        self.assertEqual(mqtt.build_disconnect(), b"\xe0\x00")

    def test_remaining_length_encodes_contract_values(self):
        for value, expected in REMAINING_CASES:
            with self.subTest(value=value):
                self.assertEqual(mqtt.encode_remaining_length(value), expected)

    def test_remaining_length_round_trip_with_offset(self):
        for value, _ in REMAINING_CASES:
            encoded = mqtt.encode_remaining_length(value)
            with self.subTest(value=value):
                self.assertEqual(mqtt.decode_remaining_length(encoded, 0), (value, len(encoded)))
                self.assertEqual(mqtt.decode_remaining_length(b"\xaa" + encoded, 1), (value, len(encoded)))

    def test_remaining_length_out_of_range_is_refused(self):
        for value in (-1, 268435456):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    mqtt.encode_remaining_length(value)

    def test_mqtt_error_keeps_the_connack_code(self):
        self.assertEqual(mqtt.MqttError(5).code, 5)


class EnabledTest(unittest.TestCase):
    def test_no_host_means_disabled(self):
        for settings in ({}, {"mqtt_host": ""}, {"mqtt_host": None}, {"mqtt_host": 1883}):
            with self.subTest(settings=settings):
                self.assertFalse(make_bridge(settings).enabled())

    def test_host_means_enabled(self):
        self.assertTrue(make_bridge({"mqtt_host": "broker.test"}).enabled())


class NoBrokerTest(unittest.TestCase):
    def test_run_without_broker_returns_without_connecting(self):
        calls = []
        bridge = make_bridge({}, client_factory=lambda: calls.append("connect"))
        bridge.run(threading.Event())
        self.assertEqual(calls, [])

    def test_tls_without_support_does_not_start(self):
        calls = []
        settings = {"mqtt_host": "broker.test", "mqtt_tls": True}
        bridge = make_bridge(settings, client_factory=lambda: calls.append("connect"))
        bridge.run(threading.Event())
        self.assertEqual(calls, [])


class CommandTest(unittest.TestCase):
    def test_on_queues_the_output_command(self):
        bridge = make_bridge()
        bridge.on_message(COMMAND_TOPIC, b"ON")
        self.assertEqual(
            bridge.queue.pop_for_mac(FAKE_MAC),
            tasks.build_output_command(FAKE_MAC, 1, 1),
        )

    def test_off_queues_the_output_command_with_zero(self):
        bridge = make_bridge()
        bridge.on_message(COMMAND_TOPIC, b"OFF")
        self.assertEqual(
            bridge.queue.pop_for_mac(FAKE_MAC),
            tasks.build_output_command(FAKE_MAC, 1, 0),
        )

    def test_port_number_is_read_from_the_topic(self):
        bridge = make_bridge()
        bridge.on_message(f"{PREFIX}/{FAKE_MAC}/3/output/set", b"ON")
        self.assertEqual(
            bridge.queue.pop_for_mac(FAKE_MAC),
            tasks.build_output_command(FAKE_MAC, 3, 1),
        )

    def test_invalid_payload_queues_nothing(self):
        for payload in (b"on", b"1", b"", b"ON "):
            with self.subTest(payload=payload):
                bridge = make_bridge()
                bridge.on_message(COMMAND_TOPIC, payload)
                self.assertIsNone(bridge.queue.pop_for_mac(FAKE_MAC))

    def test_bad_device_id_or_port_queues_nothing(self):
        topics = [
            f"{PREFIX}/00272200000g/1/output/set",
            f"{PREFIX}/0027220000012/1/output/set",
            f"{PREFIX}/{FAKE_MAC}/x/output/set",
            f"{PREFIX}/{FAKE_MAC}/0/output/set",
            f"{PREFIX}/{FAKE_MAC}/256/output/set",
            f"{PREFIX}/{FAKE_MAC}/-1/output/set",
            f"{PREFIX}/{FAKE_MAC}/1a/output/set",
        ]
        for topic in topics:
            with self.subTest(topic=topic):
                bridge = make_bridge()
                bridge.on_message(topic, b"ON")
                self.assertIsNone(bridge.queue.pop_for_mac(FAKE_MAC))

    def test_unrelated_topics_queue_nothing(self):
        topics = [
            f"other/{FAKE_MAC}/1/output/set",
            f"{PREFIX}/{FAKE_MAC}/1/output",
            f"{PREFIX}/{FAKE_MAC}/1/output/set/extra",
            "homeassistant/status",
        ]
        for topic in topics:
            with self.subTest(topic=topic):
                bridge = make_bridge()
                bridge.on_message(topic, b"ON")
                self.assertIsNone(bridge.queue.pop_for_mac(FAKE_MAC))

    def test_on_message_never_raises(self):
        bridge = make_bridge()
        self.assertIsNone(bridge.on_message(COMMAND_TOPIC, None))
        self.assertIsNone(bridge.on_message(COMMAND_TOPIC, ["ON"]))
        self.assertIsNone(bridge.queue.pop_for_mac(FAKE_MAC))


class ConnectedBridgeTest(unittest.TestCase):
    def test_on_connect_subscribes_and_publishes_retained(self):
        fake = FakeClient()
        device = {"mac": FAKE_MAC, "model": "P1E"}
        bridge = make_bridge(
            {"mqtt_host": "broker.test", "mqtt_topic_prefix": PREFIX},
            devices=[device],
            latest=lambda mac: {1: {"output": True}},
            client_factory=lambda: fake,
        )
        bridge.run(threading.Event())
        self.assertEqual(fake.subscribed, [[f"{PREFIX}/+/+/output/set"]])
        topics = dict((topic, payload) for topic, payload, _ in fake.published)
        self.assertIn(f"homeassistant/switch/mfi_{FAKE_MAC}/1_output/config", topics)
        self.assertEqual(topics[f"{PREFIX}/{FAKE_MAC}/availability"], b"online")
        self.assertEqual(topics[f"{PREFIX}/{FAKE_MAC}/1/output"], b"ON")
        self.assertTrue(all(retain for _, _, retain in fake.published))

    def test_tick_republishes_states_every_interval(self):
        fake = FakeClient()
        device = {"mac": FAKE_MAC, "model": "P1E"}
        bridge = make_bridge(
            {"mqtt_host": "broker.test", "mqtt_topic_prefix": PREFIX},
            devices=[device],
            latest=lambda mac: {1: {"output": False}},
            client_factory=lambda: fake,
        )
        bridge.run(threading.Event())
        on_tick, interval = fake.loop_args
        self.assertEqual(interval, mqtt.REPUBLISH_INTERVAL_S)
        before = len(fake.published)
        on_tick()
        self.assertGreater(len(fake.published), before)
        self.assertIn((f"{PREFIX}/{FAKE_MAC}/1/output", b"OFF", True), fake.published)


if __name__ == "__main__":
    unittest.main()

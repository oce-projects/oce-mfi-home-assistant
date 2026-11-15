"""Tests of the MQTT bridge with a fake client: commands, availability and discovery.

No network and no real broker: the fake client only records the calls.
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from mfi_server.bridge import MqttBridge
from mfi_server.commands import CommandQueue
from mfi_server.config import Settings
from mfi_server.measurements import Measurements
from mfi_server.states import DeviceStates
from mfi_server.store import DeviceStore

MAC = "02aabbccdd01"


class FakeClient:
    """Records publish, subscribe, connect and loop calls; never opens a socket."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, int, bool]] = []
        self.subscribed: list[list[str]] = []
        self.calls: list[str] = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))

    def subscribe(self, topics):
        self.calls.append("subscribe")
        self.subscribed.append(list(topics))

    def connect(self):
        self.calls.append("connect")

    def loop_forever(self, stop_event):
        self.calls.append("loop_forever")


class FakeClock:
    """A clock that only moves when the test sets now."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class BridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DeviceStore(Path(tmp.name))
        self.store.upsert(
            {
                "mac": MAC,
                "model": "test-model",
                "name": "test device",
                "authkey": "",
                "ports": [
                    {"port": 1, "sensor_id": "sensor-1", "label": "outlet 1", "model": "test-model"},
                    {"port": 2, "sensor_id": "sensor-2", "label": "outlet 2", "model": "test-model"},
                ],
            }
        )
        self.clock = FakeClock(0.0)
        self.states = DeviceStates(clock=self.clock)
        self.queue = CommandQueue()
        self.measurements = Measurements()
        self.client = FakeClient()
        self.settings = Settings(data_dir=Path(tmp.name))
        self.bridge = MqttBridge(
            self.client, self.store, self.states, self.queue, self.measurements, self.settings, self.clock
        )

    def test_on_queues_output_one_for_port_one(self):
        self.bridge.on_message("mfi/02aabbccdd01/1/output/set", b"ON")
        command = self.queue.pop(MAC)
        self.assertIsNotNone(command)
        self.assertEqual(command["port"], 1)
        self.assertEqual(command["sensor_id"], "sensor-1")
        self.assertEqual(command["value"], 1)

    def test_off_queues_output_zero_for_port_two(self):
        self.bridge.on_message("mfi/02aabbccdd01/2/output/set", b"OFF")
        command = self.queue.pop(MAC)
        self.assertIsNotNone(command)
        self.assertEqual(command["port"], 2)
        self.assertEqual(command["sensor_id"], "sensor-2")
        self.assertEqual(command["value"], 0)

    def test_other_payload_queues_nothing_and_does_not_raise(self):
        self.bridge.on_message("mfi/02aabbccdd01/1/output/set", b"FOO")
        self.assertIsNone(self.queue.pop(MAC))

    def test_unknown_device_or_port_queues_nothing(self):
        self.bridge.on_message("mfi/02aabbccdd01/9/output/set", b"ON")
        self.bridge.on_message("mfi/02aabbccdd02/1/output/set", b"ON")
        self.assertIsNone(self.queue.pop(MAC))
        self.assertIsNone(self.queue.pop("02aabbccdd02"))

    def test_malformed_command_topic_queues_nothing(self):
        self.bridge.on_message("mfi/02aabbccdd01/x/output/set", b"ON")
        self.bridge.on_message("other/02aabbccdd01/1/output/set", b"ON")
        self.assertIsNone(self.queue.pop(MAC))

    def test_connected_device_is_published_online(self):
        self.states.seen(MAC)
        self.clock.now = 10
        self.client.published.clear()
        self.bridge.publish_states()
        self.assertIn((f"mfi/{MAC}/availability", b"online", 0, True), self.client.published)

    def test_lost_device_is_published_offline(self):
        self.states.seen(MAC)
        self.clock.now = 121
        self.client.published.clear()
        self.bridge.publish_states()
        self.assertIn((f"mfi/{MAC}/availability", b"offline", 0, True), self.client.published)

    def test_online_status_republishes_all_discovery_retained(self):
        self.client.published.clear()
        self.bridge.on_message("homeassistant/status", b"online")
        topics = [topic for topic, _, _, _ in self.client.published]
        configs = [topic for topic in topics if topic.endswith("/config")]
        self.assertEqual(len(configs), 12)
        self.assertIn(f"homeassistant/switch/mfi_{MAC}/1_output/config", topics)
        self.assertTrue(all(retain for _, _, _, retain in self.client.published))

    def test_offline_status_does_not_republish_discovery(self):
        self.client.published.clear()
        self.bridge.on_message("homeassistant/status", b"offline")
        self.assertEqual(self.client.published, [])

    def test_run_connects_subscribes_publishes_and_loops_until_stopped(self):
        stop = threading.Event()
        stop.set()
        self.bridge.run(stop)
        self.assertEqual(self.client.calls[0], "connect")
        self.assertEqual(self.client.calls[1], "subscribe")
        self.assertEqual(self.client.subscribed[0], ["mfi/+/+/output/set", "homeassistant/status"])
        self.assertEqual(self.client.calls[-1], "loop_forever")
        self.assertIn(("mfi/status", b"online", 0, True), self.client.published)


if __name__ == "__main__":
    unittest.main()

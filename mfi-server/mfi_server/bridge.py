"""MQTT bridge of mfi-server: Home Assistant discovery, device states and commands.

The bridge publishes the discovery messages, the availability and the last
measurements of every device, and turns ON/OFF messages into output commands
through OutputControl. OutputControl queues the command and sends the wake-up
packet when the device's connect_request address is known, so the output
changes at once. Standard library only.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable

from mfi_server.config import Settings
from mfi_server.control import OutputControl
from mfi_server.discovery import discovery_messages
from mfi_server.measurements import Measurements
from mfi_server.states import DeviceStates
from mfi_server.store import DeviceStore

logger = logging.getLogger(__name__)

STATUS_ONLINE = b"online"
STATUS_OFFLINE = b"offline"
COMMAND_VALUES = {b"ON": 1, b"OFF": 0}
REPUBLISH_INTERVAL_S = 15.0


class MqttBridge:
    """Connects the device archive, the states, the queue and the measurements to an MQTT broker."""

    def __init__(
        self,
        client,
        store: DeviceStore,
        states: DeviceStates,
        control: OutputControl,
        measurements: Measurements,
        settings: Settings,
        clock: Callable[[], float],
    ) -> None:
        self.client = client
        self.store = store
        self.states = states
        self.control = control
        self.measurements = measurements
        self.settings = settings
        self.clock = clock

    def publish_discovery(self) -> None:
        """Publish the retained discovery config of every port, then the retained online status."""
        discovery_prefix = self.settings.mqtt_discovery_prefix
        topic_prefix = self.settings.mqtt_topic_prefix
        for device in self.store.all():
            for topic, config in discovery_messages(device, discovery_prefix, topic_prefix):
                payload = json.dumps(config, sort_keys=True).encode("utf-8")
                self.client.publish(topic, payload, retain=True)
        self.client.publish(f"{topic_prefix}/status", STATUS_ONLINE, retain=True)

    def publish_states(self) -> None:
        """Publish the availability and the last value of every port of every device, retained."""
        topic_prefix = self.settings.mqtt_topic_prefix
        for device in self.store.all():
            mac = device["mac"]
            available = self.states.state(mac) == "connected"
            self.client.publish(
                f"{topic_prefix}/{mac}/availability",
                STATUS_ONLINE if available else STATUS_OFFLINE,
                retain=True,
            )
            ports_by_sensor = {port["sensor_id"]: port["port"] for port in device["ports"]}
            for sensor_id, tagmap in self.measurements.latest(mac).items():
                port_no = ports_by_sensor.get(sensor_id)
                if port_no is None:
                    continue
                for tag, value in tagmap.items():
                    if tag == "output":
                        payload = b"ON" if value else b"OFF"
                    else:
                        payload = str(value).encode("utf-8")
                    self.client.publish(f"{topic_prefix}/{mac}/{port_no}/{tag}", payload, retain=True)

    def on_message(self, topic: str, payload: bytes) -> None:
        """Handle one incoming message; it never raises, bad input is logged and ignored."""
        if topic == f"{self.settings.mqtt_discovery_prefix}/status":
            if payload == STATUS_ONLINE:
                try:
                    self.publish_discovery()
                except Exception as exc:
                    logger.warning("discovery republish failed: %s", type(exc).__name__)
            return
        if topic.endswith("/output/set"):
            self._queue_command(topic, payload)

    def _queue_command(self, topic: str, payload: bytes) -> None:
        """Queue an ON or OFF command for one output port; anything else is logged and dropped."""
        prefix = f"{self.settings.mqtt_topic_prefix}/"
        parts = topic[len(prefix):].split("/") if topic.startswith(prefix) else []
        if len(parts) != 4 or parts[2] != "output" or parts[3] != "set":
            logger.warning("command topic not recognised: %s", topic)
            return
        mac, port_text = parts[0], parts[1]
        if not (port_text.isascii() and port_text.isdigit()):
            logger.warning("command topic has no port number: %s", topic)
            return
        port_no = int(port_text)
        if payload not in COMMAND_VALUES:
            logger.warning("command payload is not ON or OFF for %s port %d", mac, port_no)
            return
        try:
            self.control.set_output(mac, port_no, COMMAND_VALUES[payload])
        except (KeyError, ValueError) as exc:
            logger.warning("command for %s port %d refused: %s", mac, port_no, type(exc).__name__)
            return
        logger.info("queued output %d for %s port %d", COMMAND_VALUES[payload], mac, port_no)

    def _on_connect(self) -> None:
        """Subscribe, publish the discovery and the states; called after every (re)connection."""
        prefix = self.settings.mqtt_topic_prefix
        self.client.subscribe([f"{prefix}/+/+/output/set", f"{self.settings.mqtt_discovery_prefix}/status"])
        self.publish_discovery()
        self.publish_states()

    def run(self, stop_event: threading.Event) -> None:
        """Serve until stop_event is set.

        loop_forever owns the connection and reconnects with a growing delay (the broker may start after
        the add-on), calls _on_connect after every connection and publish_states every REPUBLISH_INTERVAL_S seconds.
        """
        self.client.loop_forever(
            stop_event,
            on_connect=self._on_connect,
            on_tick=self.publish_states,
            tick_interval_s=REPUBLISH_INTERVAL_S,
        )

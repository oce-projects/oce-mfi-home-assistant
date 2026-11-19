"""Tests of the command queue and the wake-up packet of mfi_server_next.tasks (offline)."""
from __future__ import annotations

import socket
import unittest

from mfi_server_next import tasks

MAC = "002722000001"
OTHER_MAC = "002722000002"


class FakeSocket:
    """Stands in for a UDP socket: records the sends, or raises the given error."""

    def __init__(self, error=None):
        self.error = error
        self.sent = []

    def sendto(self, data, addr):
        if self.error is not None:
            raise self.error
        self.sent.append((data, addr))


class TestBuildWakeup(unittest.TestCase):
    """CA5: the wake-up packet is 20 bytes, starts with 0x88 0x88 and the rest is zero."""

    def test_length_is_twenty_bytes(self):
        self.assertEqual(len(tasks.build_wakeup()), 20)
        self.assertEqual(len(tasks.build_wakeup()), tasks.WAKEUP_LEN)

    def test_starts_with_0x88_0x88(self):
        packet = tasks.build_wakeup()
        self.assertEqual(packet[0], 0x88)
        self.assertEqual(packet[1], 0x88)
        self.assertEqual(packet[:2], b"\x88\x88")

    def test_rest_is_zero(self):
        self.assertEqual(tasks.build_wakeup()[2:], bytes(18))
        self.assertEqual(tasks.build_wakeup(), b"\x88\x88" + bytes(18))

    def test_wakeup_port_is_3478(self):
        self.assertEqual(tasks.WAKEUP_PORT, 3478)


class TestSendWakeup(unittest.TestCase):
    """CA5: send_wakeup sends the packet and never raises on a send error."""

    def test_sends_packet_to_the_target(self):
        sock = FakeSocket()
        tasks.send_wakeup(sock, "127.0.0.1", 3478)
        self.assertEqual(sock.sent, [(tasks.build_wakeup(), ("127.0.0.1", 3478))])

    def test_send_error_is_logged_and_not_raised(self):
        sock = FakeSocket(error=OSError("unreachable"))
        with self.assertLogs("mfi_server_next.tasks", level="WARNING"):
            tasks.send_wakeup(sock, "127.0.0.1", 3478)
        self.assertEqual(sock.sent, [])

    def test_real_loopback_socket_receives_the_packet(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            receiver.bind(("127.0.0.1", 0))
            receiver.settimeout(5)
            port = receiver.getsockname()[1]
            tasks.send_wakeup(sender, "127.0.0.1", port)
            data, _ = receiver.recvfrom(64)
        self.assertEqual(data, tasks.build_wakeup())


class TestBuildOutputCommand(unittest.TestCase):
    """The output command has the fixed fields and keeps the extra fields."""

    def test_fields_of_the_command(self):
        self.assertEqual(
            tasks.build_output_command(MAC, 1, 1),
            {"_type": "cmd", "cmd": "mfi-output", "mac": MAC, "port": 1, "val": 1},
        )

    def test_extra_fields_are_added(self):
        command = tasks.build_output_command(MAC, 2, 0, timer=5)
        self.assertEqual(command["timer"], 5)
        self.assertEqual(command["port"], 2)
        self.assertEqual(command["val"], 0)


class TestTaskQueueOrder(unittest.TestCase):
    """CA4: commands of one mac come out in FIFO order, each one only once."""

    def test_two_tasks_come_out_in_order_once(self):
        queue = tasks.TaskQueue()
        first = tasks.build_output_command(MAC, 1, 1)
        second = tasks.build_output_command(MAC, 2, 0)
        queue.enqueue(first)
        queue.enqueue(second)
        self.assertEqual(queue.pop_for_mac(MAC), first)
        self.assertEqual(queue.pop_for_mac(MAC), second)
        self.assertIsNone(queue.pop_for_mac(MAC))

    def test_unknown_mac_gives_none(self):
        queue = tasks.TaskQueue()
        queue.enqueue(tasks.build_output_command(MAC, 1, 1))
        self.assertIsNone(queue.pop_for_mac(OTHER_MAC))
        self.assertIsNone(queue.pop_for_mac(None))

    def test_empty_queue_gives_none(self):
        self.assertIsNone(tasks.TaskQueue().pop_for_mac(MAC))

    def test_macs_are_independent(self):
        queue = tasks.TaskQueue()
        queue.enqueue(tasks.build_output_command(MAC, 1, 1))
        queue.enqueue(tasks.build_output_command(OTHER_MAC, 1, 0))
        self.assertEqual(queue.pop_for_mac(OTHER_MAC)["val"], 0)
        self.assertEqual(queue.pop_for_mac(MAC)["val"], 1)
        self.assertIsNone(queue.pop_for_mac(MAC))
        self.assertIsNone(queue.pop_for_mac(OTHER_MAC))

    def test_other_commands_are_not_replaced(self):
        queue = tasks.TaskQueue()
        queue.enqueue({"mac": MAC, "cmd": "locate", "port": 1})
        queue.enqueue({"mac": MAC, "cmd": "locate", "port": 1})
        self.assertIsNotNone(queue.pop_for_mac(MAC))
        self.assertIsNotNone(queue.pop_for_mac(MAC))
        self.assertIsNone(queue.pop_for_mac(MAC))

    def test_task_without_mac_is_rejected(self):
        queue = tasks.TaskQueue()
        for bad in ({}, {"mac": None}, None):
            with self.subTest(task=bad):
                with self.assertRaises(ValueError):
                    queue.enqueue(bad)


class TestTaskQueueReplace(unittest.TestCase):
    """The newest mfi-output replaces the queued one for the same port."""

    def test_same_port_leaves_one_task_with_the_newest_value(self):
        queue = tasks.TaskQueue()
        queue.enqueue(tasks.build_output_command(MAC, 1, 1))
        queue.enqueue(tasks.build_output_command(MAC, 1, 0))
        task = queue.pop_for_mac(MAC)
        self.assertEqual(task["port"], 1)
        self.assertEqual(task["val"], 0)
        self.assertIsNone(queue.pop_for_mac(MAC))

    def test_replacement_keeps_the_position_of_the_old_task(self):
        queue = tasks.TaskQueue()
        queue.enqueue(tasks.build_output_command(MAC, 1, 1))
        second = tasks.build_output_command(MAC, 2, 1)
        queue.enqueue(second)
        queue.enqueue(tasks.build_output_command(MAC, 1, 0))
        first_out = queue.pop_for_mac(MAC)
        self.assertEqual((first_out["port"], first_out["val"]), (1, 0))
        self.assertEqual(queue.pop_for_mac(MAC), second)
        self.assertIsNone(queue.pop_for_mac(MAC))


if __name__ == "__main__":
    unittest.main()

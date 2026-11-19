"""CA6: firmware_for_model and build_upgrade of mfi_server_next (standard library only).

Run with the suite of mfi-server:
    python3 -m unittest discover -s mfi-server/tests_next -t mfi-server -v
"""
import unittest

from mfi_server_next import firmware

EXPECTED_MODELS = {"IWD1U", "P1E", "IWO2U", "P8U", "M2S", "M2M", "P6E", "P1U", "P3E", "P3U"}
NO_FIRMWARE_MODELS = ("IWS1U", "EM3", "EM24", "THERM")


class TestFirmwareForModel(unittest.TestCase):
    def test_table_has_the_ten_models(self):
        self.assertEqual(set(firmware.FIRMWARE_MODELS), EXPECTED_MODELS)
        self.assertEqual(len(firmware.FIRMWARE_MODELS), 10)

    def test_every_table_model_gets_the_version(self):
        for model in sorted(EXPECTED_MODELS):
            with self.subTest(model=model):
                self.assertEqual(firmware.firmware_for_model(model), "2.1.11.1309")

    def test_models_without_firmware_return_none(self):
        for model in NO_FIRMWARE_MODELS:
            with self.subTest(model=model):
                self.assertIsNone(firmware.firmware_for_model(model))

    def test_iws1u_has_no_firmware(self):
        self.assertIsNone(firmware.firmware_for_model("IWS1U"))

    def test_none_has_no_firmware(self):
        self.assertIsNone(firmware.firmware_for_model(None))
        self.assertIsNone(firmware.firmware_for_model())

    def test_empty_and_lowercase_models_have_no_firmware(self):
        self.assertIsNone(firmware.firmware_for_model(""))
        self.assertIsNone(firmware.firmware_for_model("m2m"))


class TestBuildUpgrade(unittest.TestCase):
    def test_m2m_message(self):
        self.assertEqual(
            firmware.build_upgrade("M2M"),
            {
                "_type": "upgrade",
                "url": "http://mfi-server:6080/dl/firmware/M2M/2.1.11.1309/firmware.bin",
                "version": "2.1.11.1309",
            },
        )

    def test_every_table_model_gets_the_same_path(self):
        for model in sorted(EXPECTED_MODELS):
            with self.subTest(model=model):
                message = firmware.build_upgrade(model)
                self.assertEqual(message["_type"], "upgrade")
                self.assertEqual(
                    message["url"],
                    "http://mfi-server:6080/dl/firmware/M2M/2.1.11.1309/firmware.bin",
                )
                self.assertEqual(message["version"], "2.1.11.1309")

    def test_host_and_port_are_used(self):
        message = firmware.build_upgrade("P1E", host="example.test", port=8080)
        self.assertEqual(
            message["url"],
            "http://example.test:8080/dl/firmware/M2M/2.1.11.1309/firmware.bin",
        )

    def test_models_without_firmware_return_none(self):
        for model in NO_FIRMWARE_MODELS:
            with self.subTest(model=model):
                self.assertIsNone(firmware.build_upgrade(model))

    def test_iws1u_gets_no_upgrade(self):
        self.assertIsNone(firmware.build_upgrade("IWS1U"))

    def test_none_model_gets_no_upgrade(self):
        self.assertIsNone(firmware.build_upgrade(None))

    def test_no_argument_does_not_raise(self):
        self.assertIsNone(firmware.build_upgrade())


if __name__ == "__main__":
    unittest.main()

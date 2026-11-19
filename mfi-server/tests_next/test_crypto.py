"""Tests for mfi_server_next.crypto: AES-128-CBC and PBKDF2 (standard library only)."""
import hashlib
import unittest

from mfi_server_next import crypto

FIPS_KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
FIPS_PLAIN = bytes.fromhex("00112233445566778899aabbccddeeff")
FIPS_CIPHER = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
ZERO_IV = b"\x00" * 16
FAKE_KEY = b"0123456789abcdef"
FAKE_IV = b"fedcba9876543210"
INFORM_PLAIN = b'{"name":"fake-device-0001"}'


class TestAes128(unittest.TestCase):
    def test_fips_197_decrypt(self):
        self.assertEqual(crypto.aes128_decrypt(FIPS_KEY, ZERO_IV, FIPS_CIPHER, unpad=False), FIPS_PLAIN)

    def test_fips_197_encrypt(self):
        self.assertEqual(crypto.aes128_encrypt(FIPS_KEY, ZERO_IV, FIPS_PLAIN, pad=False), FIPS_CIPHER)

    def test_inform_round_trip(self):
        cipher = crypto.aes128_encrypt(FAKE_KEY, FAKE_IV, INFORM_PLAIN)
        self.assertEqual(len(cipher), 32)
        self.assertEqual(crypto.aes128_decrypt(FAKE_KEY, FAKE_IV, cipher), INFORM_PLAIN)

    def test_unpad_false_keeps_padding_bytes(self):
        cipher = crypto.aes128_encrypt(FAKE_KEY, FAKE_IV, INFORM_PLAIN)
        raw = crypto.aes128_decrypt(FAKE_KEY, FAKE_IV, cipher, unpad=False)
        self.assertEqual(raw, INFORM_PLAIN + b"\x05" * 5)

    def test_empty_data_with_padding_round_trip(self):
        cipher = crypto.aes128_encrypt(FAKE_KEY, FAKE_IV, b"")
        self.assertEqual(cipher, crypto.aes128_encrypt(FAKE_KEY, FAKE_IV, b"", pad=True))
        self.assertEqual(len(cipher), 16)
        self.assertEqual(crypto.aes128_decrypt(FAKE_KEY, FAKE_IV, cipher), b"")

    def test_invalid_padding_raises(self):
        cipher = crypto.aes128_encrypt(FAKE_KEY, FAKE_IV, b"a" * 15 + b"\x00", pad=False)
        with self.assertRaises(ValueError):
            crypto.aes128_decrypt(FAKE_KEY, FAKE_IV, cipher)

    def test_empty_data_without_padding_raises(self):
        with self.assertRaises(ValueError):
            crypto.aes128_encrypt(FAKE_KEY, FAKE_IV, b"", pad=False)

    def test_data_not_multiple_of_16_raises(self):
        with self.assertRaises(ValueError):
            crypto.aes128_decrypt(FAKE_KEY, FAKE_IV, b"x" * 15)
        with self.assertRaises(ValueError):
            crypto.aes128_encrypt(FAKE_KEY, FAKE_IV, b"x" * 17, pad=False)

    def test_bad_key_and_iv_length_raise(self):
        with self.assertRaises(ValueError):
            crypto.aes128_decrypt(b"k" * 15, FAKE_IV, FIPS_CIPHER)
        with self.assertRaises(ValueError):
            crypto.aes128_encrypt(FAKE_KEY, b"v" * 17, INFORM_PLAIN)

    def test_wrong_key_sizes_raise(self):
        with self.assertRaises(ValueError):
            crypto.aes128_decrypt(b"", FAKE_IV, FIPS_CIPHER)
        with self.assertRaises(ValueError):
            crypto.aes128_encrypt(b"k" * 32, FAKE_IV, INFORM_PLAIN)
        with self.assertRaises(ValueError):
            crypto.aes128_encrypt(FAKE_KEY, b"", INFORM_PLAIN)


class TestPbkdf2(unittest.TestCase):
    def test_verify_accepts_right_password_and_rejects_wrong(self):
        h = crypto.pbkdf2_hash("CorrectHorse1!", iterations=1000)
        self.assertTrue(crypto.pbkdf2_verify("CorrectHorse1!", h))
        self.assertFalse(crypto.pbkdf2_verify("wrong", h))
        self.assertFalse(crypto.pbkdf2_verify("x", "not-a-hash"))

    def test_hash_format_and_digest_value(self):
        h = crypto.pbkdf2_hash("pw", salt=bytes(16), iterations=1000)
        fields = h.split("$")
        self.assertEqual(len(fields), 4)
        self.assertEqual(fields[0], "pbkdf2_sha256")
        self.assertEqual(fields[1], "1000")
        self.assertEqual(fields[2], "00" * 16)
        expected = hashlib.pbkdf2_hmac("sha256", b"pw", bytes(16), 1000).hex()
        self.assertEqual(fields[3], expected)

    def test_random_salt_is_16_bytes_and_differs(self):
        first = crypto.pbkdf2_hash("same", iterations=1000).split("$")[2]
        second = crypto.pbkdf2_hash("same", iterations=1000).split("$")[2]
        self.assertEqual(len(first), 32)
        self.assertNotEqual(first, second)

    def test_zero_iterations_raises(self):
        with self.assertRaises(ValueError):
            crypto.pbkdf2_hash("x", iterations=0)

    def test_empty_and_non_ascii_password(self):
        h_empty = crypto.pbkdf2_hash("", iterations=1000)
        self.assertTrue(crypto.pbkdf2_verify("", h_empty))
        self.assertFalse(crypto.pbkdf2_verify(" ", h_empty))
        h_accent = crypto.pbkdf2_hash("àèìòù1!", iterations=1000)
        self.assertTrue(crypto.pbkdf2_verify("àèìòù1!", h_accent))
        self.assertFalse(crypto.pbkdf2_verify("aeiou1!", h_accent))

    def test_malformed_stored_values_return_false(self):
        valid = crypto.pbkdf2_hash("pw", salt=bytes(16), iterations=1000)
        fields = valid.split("$")
        malformed = [
            "",
            "pbkdf2_sha256",
            "pbkdf2_sha256$1000$00",
            "pbkdf2_sha256$1000$00$00$extra",
            "pbkdf2_sha256$abc$" + fields[2] + "$" + fields[3],
            "pbkdf2_sha256$-1000$" + fields[2] + "$" + fields[3],
            "pbkdf2_sha256$0$" + fields[2] + "$" + fields[3],
            "pbkdf2_sha256$1000$zz$" + fields[3],
            "pbkdf2_sha256$1000$" + fields[2] + "$" + fields[3][:-1],
            "pbkdf2_sha256$1000$0 0$" + fields[3],
            "md5$1000$" + fields[2] + "$" + fields[3],
        ]
        for stored in malformed:
            with self.subTest(stored=stored):
                self.assertFalse(crypto.pbkdf2_verify("pw", stored))

    def test_non_string_stored_returns_false(self):
        self.assertFalse(crypto.pbkdf2_verify("pw", None))
        self.assertFalse(crypto.pbkdf2_verify("pw", 12345))

    def test_wrong_algorithm_with_right_digest_returns_false(self):
        valid = crypto.pbkdf2_hash("pw", salt=bytes(16), iterations=1000)
        renamed = valid.replace("pbkdf2_sha256", "pbkdf2_sha512", 1)
        self.assertFalse(crypto.pbkdf2_verify("pw", renamed))


if __name__ == "__main__":
    unittest.main()

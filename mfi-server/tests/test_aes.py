"""Tests for the pure Python AES-128 implementation (aes.py).

Vectors: FIPS-197 Appendix C.1 and NIST SP 800-38A F.2.1 / F.2.2 (CBC-AES128).
"""
from __future__ import annotations

import os
import unittest

from mfi_server import aes

FIPS_KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
FIPS_PLAIN = bytes.fromhex("00112233445566778899aabbccddeeff")
FIPS_CIPHER = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")

SP_KEY = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
SP_IV = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
SP_PLAIN = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a" "ae2d8a571e03ac9c9eb76fac45af8e51")
SP_CIPHER = bytes.fromhex("7649abac8119b246cee98e9b12e9197d" "5086cb9b507219ee95db113a917678b2")


class TestBlockCipher(unittest.TestCase):
    def test_fips_197_encrypt(self):
        self.assertEqual(aes.encrypt_block(FIPS_KEY, FIPS_PLAIN), FIPS_CIPHER)

    def test_fips_197_decrypt(self):
        self.assertEqual(aes.decrypt_block(FIPS_KEY, FIPS_CIPHER), FIPS_PLAIN)

    def test_block_roundtrip_with_random_key(self):
        key = os.urandom(16)
        block = os.urandom(16)
        self.assertEqual(aes.decrypt_block(key, aes.encrypt_block(key, block)), block)

    def test_returns_bytes_of_block_size(self):
        out = aes.encrypt_block(FIPS_KEY, FIPS_PLAIN)
        self.assertIsInstance(out, bytes)
        self.assertEqual(len(out), 16)

    def test_bad_key_length_raises(self):
        for size in (0, 15, 17, 24, 32):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    aes.encrypt_block(bytes(size), FIPS_PLAIN)
                with self.assertRaises(ValueError):
                    aes.decrypt_block(bytes(size), FIPS_CIPHER)

    def test_bad_block_length_raises(self):
        for size in (0, 15, 17):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    aes.encrypt_block(FIPS_KEY, bytes(size))
                with self.assertRaises(ValueError):
                    aes.decrypt_block(FIPS_KEY, bytes(size))

    def test_error_message_does_not_contain_key(self):
        short_key = FIPS_KEY[:15]
        with self.assertRaises(ValueError) as ctx:
            aes.encrypt_block(short_key, FIPS_PLAIN)
        self.assertNotIn(short_key.hex(), str(ctx.exception))


class TestCbc(unittest.TestCase):
    def test_sp800_38a_encrypt(self):
        self.assertEqual(aes.encrypt_cbc(SP_KEY, SP_IV, SP_PLAIN), SP_CIPHER)

    def test_sp800_38a_decrypt(self):
        self.assertEqual(aes.decrypt_cbc(SP_KEY, SP_IV, SP_CIPHER), SP_PLAIN)

    def test_single_block_is_first_cipher_block(self):
        self.assertEqual(aes.encrypt_cbc(SP_KEY, SP_IV, SP_PLAIN[:16]), SP_CIPHER[:16])

    def test_identical_blocks_chain_to_different_output(self):
        out = aes.encrypt_cbc(SP_KEY, SP_IV, b"A" * 32)
        self.assertNotEqual(out[:16], out[16:])

    def test_roundtrip_with_padding_and_random_key(self):
        key = os.urandom(16)
        iv = os.urandom(16)
        cipher = aes.encrypt_cbc(key, iv, aes.pkcs7_pad(b"hello mfi"))
        self.assertEqual(aes.pkcs7_unpad(aes.decrypt_cbc(key, iv, cipher)), b"hello mfi")

    def test_data_not_multiple_of_16_raises(self):
        with self.assertRaises(ValueError):
            aes.encrypt_cbc(SP_KEY, SP_IV, b"x" * 15)
        with self.assertRaises(ValueError):
            aes.decrypt_cbc(SP_KEY, SP_IV, b"x" * 17)

    def test_empty_data_raises(self):
        with self.assertRaises(ValueError):
            aes.encrypt_cbc(SP_KEY, SP_IV, b"")
        with self.assertRaises(ValueError):
            aes.decrypt_cbc(SP_KEY, SP_IV, b"")

    def test_bad_key_and_iv_length_raise(self):
        cases = {
            "key 15": (SP_KEY[:15], SP_IV),
            "key 17": (SP_KEY + b"\x00", SP_IV),
            "iv 15": (SP_KEY, SP_IV[:15]),
            "iv 17": (SP_KEY, SP_IV + b"\x00"),
        }
        for name, (key, iv) in cases.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    aes.encrypt_cbc(key, iv, SP_PLAIN)
                with self.assertRaises(ValueError):
                    aes.decrypt_cbc(key, iv, SP_CIPHER)


class TestPkcs7(unittest.TestCase):
    def test_pad_empty_is_one_full_block(self):
        self.assertEqual(aes.pkcs7_pad(b""), b"\x10" * 16)

    def test_pad_fifteen_adds_one_byte(self):
        padded = aes.pkcs7_pad(b"a" * 15)
        self.assertEqual(len(padded), 16)
        self.assertEqual(padded[-1], 1)

    def test_pad_full_block_adds_block(self):
        padded = aes.pkcs7_pad(b"a" * 16)
        self.assertEqual(len(padded), 32)
        self.assertEqual(padded[:16], b"a" * 16)
        self.assertEqual(padded[16:], b"\x10" * 16)

    def test_unpad_inverts_pad(self):
        samples = [
            b"",
            b"a",
            b"a" * 15,
            b"a" * 16,
            b"hello mfi",
            "àèì".encode("utf-8"),
            bytes(range(256)),
        ]
        for sample in samples:
            with self.subTest(length=len(sample)):
                self.assertEqual(aes.pkcs7_unpad(aes.pkcs7_pad(sample)), sample)

    def test_unpad_accepts_valid_padding(self):
        self.assertEqual(aes.pkcs7_unpad(b"a" * 14 + b"\x02\x02"), b"a" * 14)
        self.assertEqual(aes.pkcs7_unpad(b"\x10" * 16), b"")

    def test_unpad_rejects_invalid_padding(self):
        samples = [
            b"",
            b"a" * 15,
            b"a" * 17,
            b"a" * 15 + b"\x00",
            b"a" * 15 + b"\x11",
            b"a" * 14 + b"\x01\x02",
            b"\x00" * 16,
            b"\x11" * 16,
        ]
        for sample in samples:
            with self.subTest(length=len(sample), last=sample[-1:]):
                with self.assertRaises(ValueError) as ctx:
                    aes.pkcs7_unpad(sample)
                self.assertEqual(str(ctx.exception), "invalid padding")


if __name__ == "__main__":
    unittest.main()

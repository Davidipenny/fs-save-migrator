"""AES-128-CBC 加解密测试"""
import pytest

from fs_save_migrator import HAS_CRYPTOGRAPHY, aes_decrypt, aes_encrypt
from tests.conftest import TEST_IV, TEST_KEY


def test_aes_round_trip():
    plain = b"Hello Dark Souls Save File!" + b"\x00" * 5  # 32 字节
    ct = aes_encrypt(plain, TEST_IV, TEST_KEY)
    assert ct and ct != plain
    assert aes_decrypt(ct, TEST_IV, TEST_KEY) == plain


def test_aes_round_trip_no_padding():
    """NoPadding 语义：对齐输入可逆，且密文长度 == 明文长度（无填充字节）。"""
    plain = b"x" * 0x2E0
    ct = aes_encrypt(plain, TEST_IV, TEST_KEY)
    assert len(ct) == len(plain)
    assert aes_decrypt(ct, TEST_IV, TEST_KEY) == plain


def test_aes_non_aligned_input_raises():
    """NoPadding：非 16 倍数输入必须显式报错（真实存档均为对齐明文）。"""
    with pytest.raises(ValueError):
        aes_encrypt(b"x" * 0x2E1, TEST_IV, TEST_KEY)


def test_aes_wrong_key_produces_garbage():
    """NoPadding：错钥解密不抛异常，但产出与原文不同的乱码。"""
    plain = b"secret data here!" + b"\x00" * 15  # 32 字节对齐
    ct = aes_encrypt(plain, TEST_IV, TEST_KEY)
    wrong = aes_decrypt(ct, TEST_IV, b"\x00" * 16)
    assert wrong != plain


@pytest.mark.skipif(not HAS_CRYPTOGRAPHY, reason="cryptography 未安装")
def test_cryptography_available():
    assert HAS_CRYPTOGRAPHY

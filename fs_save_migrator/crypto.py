"""AES-128-CBC（无填充）加解密
=============================

优先使用 cryptography 库；缺失时回退 PowerShell + .NET（仅 Windows，较慢）。
回退路径显式失败（不再静默返回空结果）。

**无填充（NoPadding）的原因（实测结论）**：FromSoftware 真实存档的明文
本就 16 字节对齐、无 PKCS7 填充字节（DS3/NR/Sekiro 真实存档实测：
PKCS7 unpad 会失败）。cryptography 43+ 移除了隐式填充，行为恰为裸 CBC，
与真实存档格式一致；显式声明无填充以在所有版本保持该行为。
输入必须是 16 字节对齐，否则抛 ValueError。
"""
import subprocess

# 尝试导入 cryptography
try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False


# ─── AES 加解密 ────────────────────────────────────────────────────────

def aes_decrypt(ciphertext: bytes | bytearray, iv: bytes | bytearray,
                key: bytes) -> bytes:
    if HAS_CRYPTOGRAPHY:
        d = Cipher(algorithms.AES(key), modes.CBC(iv),
                   backend=default_backend()).decryptor()
        return d.update(ciphertext) + d.finalize()
    else:
        return _powershell_aes(ciphertext.hex(), iv.hex(), key.hex(), decrypt=True)


def aes_encrypt(plaintext: bytes | bytearray, iv: bytes | bytearray,
                key: bytes) -> bytes:
    if HAS_CRYPTOGRAPHY:
        e = Cipher(algorithms.AES(key), modes.CBC(iv),
                   backend=default_backend()).encryptor()
        return e.update(plaintext) + e.finalize()
    else:
        return _powershell_aes(plaintext.hex(), iv.hex(), key.hex(), decrypt=False)


def _powershell_aes(data_hex: str, iv_hex: str, key_hex: str, decrypt: bool) -> bytes:
    """PowerShell + .NET AES 回退（Windows PowerShell 5.1 兼容）。

    - hex→bytes 用自写 H2B 函数（`[System.Convert]::FromHexString` 是 .NET 5+/PS7
      专属 API，PS5.1 不存在）
    - PaddingMode.None：与 cryptography 路径一致（真实存档无 PKCS7 填充，
      明文本就 16 字节对齐；输入不对齐时 .NET 抛异常 → 显式失败）
    - 整体 try/catch：任何异常 → Write-Error + exit 1（**显式失败**，不再静默返回空）
    """
    mode_name = "Decrypt" if decrypt else "Encrypt"
    create = "CreateDecryptor" if decrypt else "CreateEncryptor"
    ps = (
        "try {"
        + "function H2B($h){$n=[int]($h.Length/2);$b=New-Object 'System.Byte[]' $n;"
        + "for($i=0;$i -lt $n;$i++){$b[$i]=[Convert]::ToByte($h.Substring($i*2,2),16)};,$b}"
        + "$k=H2B '%s';" % key_hex
        + "$i=H2B '%s';" % iv_hex
        + "$d=H2B '%s';" % data_hex
        + "$a=[System.Security.Cryptography.Aes]::Create();"
        + "$a.Mode=[System.Security.Cryptography.CipherMode]::CBC;"
        + "$a.Padding=[System.Security.Cryptography.PaddingMode]::None;"
        + "$t=$a.%s($k,$i);" % create
        + "$m=New-Object System.IO.MemoryStream;"
        + "$c=New-Object System.Security.Cryptography.CryptoStream($m,$t,"
        "[System.Security.Cryptography.CryptoStreamMode]::Write);"
        + "$c.Write($d,0,$d.Length);$c.FlushFinalBlock();$c.Close();"
        + "$b=$m.ToArray();$m.Close();"
        + "$s=New-Object System.Text.StringBuilder;"
        + "foreach($x in $b){[void]$s.Append($x.ToString('x2'))}"
        + "Write-Output $s.ToString()"
        + "} catch { Write-Error $_.Exception.Message; exit 1 }"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError("PowerShell %s 失败: %s"
                           % (mode_name, (r.stderr or r.stdout).strip()))
    out = r.stdout.strip()
    if not out:
        raise RuntimeError("PowerShell %s 返回空结果 (stderr: %s)"
                           % (mode_name, r.stderr.strip() or "(无)"))
    try:
        return bytes.fromhex(out)
    except ValueError as e:
        raise RuntimeError("PowerShell %s 返回非法 hex 输出: %r"
                           % (mode_name, out[:80])) from e

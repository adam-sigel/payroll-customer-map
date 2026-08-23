#!/usr/bin/env python3
"""Encrypt the plaintext map into the password-gated index.html.

The gate in index.html derives its key with PBKDF2-SHA256 / 100,000 iterations
/ 32 bytes and decrypts with AES-CBC, so this script must match exactly. It
reuses the existing index.html as the gate template and swaps only the PAYLOAD
line, which keeps the two in sync automatically.

Usage:  python3 encrypt.py [plaintext.html]     # prompts for the password
"""
import base64, getpass, hashlib, json, os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'map.source.html')
OUT = os.path.join(ROOT, 'index.html')

PAYLOAD_RE = re.compile(r'^const PAYLOAD = \{.*\};$', re.MULTILINE)


def pkcs7(data, block=16):
    pad = block - (len(data) % block)
    return data + bytes([pad]) * pad


def encrypt(plaintext, password):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    salt = os.urandom(32)
    iv = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100_000, 32)
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = enc.update(pkcs7(plaintext)) + enc.finalize()
    return {
        'ct': base64.b64encode(ct).decode(),
        'iv': base64.b64encode(iv).decode(),
        'salt': base64.b64encode(salt).decode(),
    }


def main():
    plaintext = open(SRC, 'rb').read()
    gate = open(OUT, encoding='utf-8').read()
    if not PAYLOAD_RE.search(gate):
        sys.exit(f'{OUT}: no PAYLOAD line found — is it still the encrypted gate?')

    pw = getpass.getpass('Map password: ')
    if pw != getpass.getpass('Confirm: '):
        sys.exit('Passwords do not match.')
    if not pw:
        sys.exit('Empty password.')

    payload = json.dumps(encrypt(plaintext, pw))
    open(OUT, 'w', encoding='utf-8').write(
        PAYLOAD_RE.sub(lambda _: f'const PAYLOAD = {payload};', gate, count=1)
    )
    print(f'Wrote {OUT} ({len(payload)} bytes of payload) from {os.path.basename(SRC)}')


if __name__ == '__main__':
    main()

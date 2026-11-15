# utils.py

from smartcard.System import readers
import hashlib
import struct
import hmac

try:
    from Crypto.Cipher import AES
except ImportError:
    raise ImportError("PyCryptodome is required: pip install pycryptodome")

# ----------- CONFIG -----------

BLOCK = 8
KEY = [0xFF] * 6
SECRET = b"super_secret_key"

# ----------- CONNECTION -----------

def connect_reader():
    r = readers()
    if not r:
        raise Exception("No reader found")
    conn = r[0].createConnection()
    conn.connect()
    return conn


def load_key(conn):
    conn.transmit([0xFF, 0x82, 0x00, 0x00, 0x06] + KEY)


def authenticate(conn, block=BLOCK):
    auth = [0xFF, 0x86, 0x00, 0x00, 0x05,
            0x01, 0x00, block, 0x60, 0x00]
    conn.transmit(auth)


# ----------- CARD OPS -----------

def read_block(conn, block=BLOCK):
    data, sw1, sw2 = conn.transmit([0xFF, 0xB0, 0x00, block, 0x10])
    return bytes(data)


def write_block(conn, data, block=BLOCK):
    conn.transmit([0xFF, 0xD6, 0x00, block, 0x10] + list(data))


def get_uid(conn):
    data, sw1, sw2 = conn.transmit([0xFF, 0xCA, 0x00, 0x00, 0x00])
    return bytes(data).hex()


# ----------- ENCODING -----------

def checksum(data):
    return hmac.new(SECRET, data, hashlib.sha256).digest()[:8]


def encode(balance, counter):
    raw = struct.pack(">II", balance, counter)
    mac = hmac.new(SECRET, raw, hashlib.sha256).digest()[:8]
    block = raw + mac
    key = hashlib.sha256(SECRET).digest()[:16]
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(block)


def decode(data):
    if len(data) != 16:
        raise Exception("Invalid data length")
    key = hashlib.sha256(SECRET).digest()[:16]
    cipher = AES.new(key, AES.MODE_ECB)
    block = cipher.decrypt(data)
    raw = block[:8]
    mac = block[8:]

    if hmac.new(SECRET, raw, hashlib.sha256).digest()[:8] != mac:
        raise Exception("Integrity check failed")

    balance, counter = struct.unpack(">II", raw)
    return balance, counter


# ----------- HIGH LEVEL -----------

def read_card():
    conn = connect_reader()
    load_key(conn)
    authenticate(conn)

    uid = get_uid(conn)
    raw = read_block(conn)

    balance, counter = decode(raw)
    return uid, balance, counter


def write_card(balance, counter):
    conn = connect_reader()
    load_key(conn)
    authenticate(conn)

    data = encode(balance, counter)
    write_block(conn, data)
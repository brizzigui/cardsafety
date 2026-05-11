import time
import json
import os
from utils import read_card, write_card

FARE = 5

# requsted at start
MACHINE_NAME = "" 
LEDGER_FILE = ""
LEDGER_LAST = {}

def load_ledger():
    """Load existing ledger entries into memory for fast lookups."""
    LEDGER_LAST.clear()
    if not LEDGER_FILE or not os.path.exists(LEDGER_FILE):
        return

    with open(LEDGER_FILE, "r") as f:
        for line in f:
            try:
                e = json.loads(line)
                uid = e.get("uid")
                counter = e.get("counter")
                if uid is None or counter is None:
                    continue
                prev = LEDGER_LAST.get(uid)
                if prev is None or counter > prev:
                    LEDGER_LAST[uid] = counter
            except Exception:
                continue

def log_state(uid, balance, counter):
    entry = {
        "machine": MACHINE_NAME,
        "uid": uid,
        "balance": balance,
        "counter": counter,
        "operation": -FARE,
        "timestamp": time.time()
    }
    # append to disk for persistence
    if not LEDGER_FILE:
        raise RuntimeError("LEDGER_FILE not set")

    with open(LEDGER_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # update in-memory ledger: keep the highest counter seen per uid
    prev = LEDGER_LAST.get(uid)
    if prev is None or counter > prev:
        LEDGER_LAST[uid] = counter


def state_seen(uid, counter):
    # Fast in-memory check: if we've seen this UID before and the
    # presented counter is <= last seen counter, it's a replay.
    prev = LEDGER_LAST.get(uid)
    if prev is not None and counter <= prev:
        return True

    # Fallback: if ledger on disk exists but memory might be stale,
    # reload and re-check.
    if LEDGER_FILE and os.path.exists(LEDGER_FILE):
        load_ledger()
        prev = LEDGER_LAST.get(uid)
        if prev is not None and counter <= prev:
            return True

    return False


def process():
    uid, balance, counter = read_card()
    print(f"{uid} → balance={balance}, counter={counter}")

    if state_seen(uid, counter):
        print("🚫 Replay detected")
        return

    if balance < FARE:
        print("🚫 Insufficient balance")
        return

    new_balance = balance - FARE
    new_counter = counter + 1

    write_card(new_balance, new_counter)
    log_state(uid, balance, counter)

    print("✅ OK")


if __name__ == "__main__":
    MACHINE_NAME = input("Input machine name: ")
    LEDGER_FILE = f"ledger_{MACHINE_NAME}.log"
    load_ledger()
    while True:
        try:
            print("Waiting for card...")
            process()
        except Exception as e:
            print("Error:", e)
        time.sleep(2)
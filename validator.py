import time
import json
import os
from utils import read_card, write_card

FARE = 5
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
        "timestamp": time.time(),
    }
    if not LEDGER_FILE:
        raise RuntimeError("LEDGER_FILE not set")
    with open(LEDGER_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    prev = LEDGER_LAST.get(uid)
    if prev is None or counter > prev:
        LEDGER_LAST[uid] = counter


def state_seen(uid, counter):
    prev = LEDGER_LAST.get(uid)
    if prev is not None and counter <= prev:
        return True
    if LEDGER_FILE and os.path.exists(LEDGER_FILE):
        load_ledger()
        prev = LEDGER_LAST.get(uid)
        if prev is not None and counter <= prev:
            return True
    return False


def process():
    """Read a card and apply fare deduction.

    Returns a dict with two keys:
      - "status": one of "ok", "replay", "insufficient", "error"
      - "message": human-readable description of the outcome
    """
    try:
        uid, balance, counter = read_card()
    except Exception as e:
        return {"status": "error", "message": str(e)}

    if state_seen(uid, counter):
        return {
            "status": "replay",
            "message": f"{uid} — replay detected (counter={counter})",
        }

    if balance < FARE:
        return {
            "status": "insufficient",
            "message": f"{uid} — insufficient balance ({balance} < {FARE})",
        }

    new_balance = balance - FARE
    new_counter = counter + 1

    try:
        write_card(new_balance, new_counter)
        log_state(uid, balance, counter)
    except Exception as e:
        return {"status": "error", "message": str(e)}

    return {
        "status": "ok",
        "message": f"{uid} — OK (balance {balance} -> {new_balance})",
    }


def run():
    """CLI wrapper: calls process() and prints a human-readable result."""
    result = process()
    status_icons = {
        "ok": "✅ OK",
        "replay": "🚫 Replay detected",
        "insufficient": "🚫 Insufficient balance",
        "error": "❌ Error",
    }
    icon = status_icons.get(result["status"], "❓ Unknown")
    print(f"{icon} — {result['message']}")


if __name__ == "__main__":
    MACHINE_NAME = input("Input machine name: ")
    LEDGER_FILE = f"ledger_{MACHINE_NAME}.log"
    load_ledger()
    while True:
        try:
            print("Waiting for card...")
            run()
        except Exception as e:
            print("Error:", e)
        time.sleep(2)
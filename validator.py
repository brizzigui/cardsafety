import time
import json
import os
from utils import read_card, write_card

FARE = 5

# requsted at start
MACHINE_NAME = "" 
LEDGER_FILE = ""

def log_state(uid, balance, counter):
    entry = {
        "machine": MACHINE_NAME,
        "uid": uid,
        "balance": balance,
        "counter": counter,
        "operation": -FARE,
        "timestamp": time.time()
    }
    with open(LEDGER_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def state_seen(uid, balance, counter):
    if not os.path.exists(LEDGER_FILE):
        return False

    with open(LEDGER_FILE, "r") as f:
        for line in f:
            e = json.loads(line)
            if (e["uid"], e["balance"], e["counter"]) == (uid, balance, counter):
                return True
    return False


def process():
    uid, balance, counter = read_card()
    print(f"{uid} → balance={balance}, counter={counter}")

    if state_seen(uid, balance, counter):
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
    while True:
        try:
            print("Waiting for card...")
            process()
        except Exception as e:
            print("Error:", e)
        time.sleep(2)
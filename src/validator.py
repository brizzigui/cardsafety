import time
import json
import os
from utils import read_card, write_card

FARE = 5

class Validator:
    def __init__(self, machine_name, ledger_file=None, security_enabled=True):
        self.machine_name = machine_name
        self.ledger_file = ledger_file
        self.security_enabled = security_enabled
        
        # In-memory mapping of UID -> highest seen counter
        self.ledger_last = {}
        self.ledger_loaded = False

        if self.security_enabled and self.ledger_file:
            self._load_ledger_once()

    def _load_ledger_once(self):
        """Loads the ledger from disk into memory EXACTLY once."""
        if self.ledger_loaded:
            return
            
        self.ledger_last.clear()
        if self.ledger_file and os.path.exists(self.ledger_file):
            with open(self.ledger_file, "r") as f:
                for line in f:
                    try:
                        e = json.loads(line.strip())
                        uid = e.get("uid")
                        counter = e.get("counter")
                        if uid is not None and counter is not None:
                            prev = self.ledger_last.get(uid, -1)
                            if counter > prev:
                                self.ledger_last[uid] = counter
                    except json.JSONDecodeError:
                        continue
        self.ledger_loaded = True

    def state_seen(self, uid, counter):
        """O(1) memory lookup to detect replays/forks."""
        if not self.security_enabled:
            return False
            
        prev = self.ledger_last.get(uid, -1)
        return counter <= prev

    def log_state(self, uid, balance, counter):
        """Update the in-memory ledger and append to the disk log."""
        if not self.security_enabled:
            return

        # 1. Update fast in-memory ledger
        prev = self.ledger_last.get(uid, -1)
        if counter > prev:
            self.ledger_last[uid] = counter

        # 2. Append directly to disk log
        if self.ledger_file:
            entry = {
                "machine": self.machine_name,
                "uid": uid,
                "balance": balance,
                "counter": counter,
                "operation": -FARE,
                "timestamp": time.time(),
            }
            with open(self.ledger_file, "a") as f:
                f.write(json.dumps(entry) + "\n")

    def process(self):
        """
        Read a card, check security constraints, apply fare, and save.
        Returns a dict: {"status": str, "message": str}
        """
        try:
            uid, balance, counter = read_card()
        except Exception as e:
            return {"status": "error", "message": f"Read error: {str(e)}"}

        if self.state_seen(uid, counter):
            return {
                "status": "replay",
                "message": f"{uid} — replay detected (counter={counter} <= previously seen)"
            }

        if balance < FARE:
            return {
                "status": "insufficient",
                "message": f"{uid} — insufficient balance ({balance} < {FARE})"
            }

        new_balance = balance - FARE
        new_counter = counter + 1

        try:
            write_card(new_balance, new_counter)
            self.log_state(uid, balance, counter)
        except Exception as e:
            return {"status": "error", "message": f"Hardware write error: {str(e)}"}

        return {
            "status": "ok",
            "message": f"{uid} — OK (balance {balance} -> {new_balance})"
        }


def run_cli():
    """Standalone CLI loop for regular terminal usage."""
    machine_name = input("Input machine name: ")
    ledger_file = f"ledger_{machine_name}.log"
    
    # Initialize the validator system
    val = Validator(machine_name, ledger_file=ledger_file)
    
    status_icons = {
        "ok": "✅ OK",
        "replay": "🚫 Replay detected",
        "insufficient": "🚫 Insufficient balance",
        "error": "❌ Error",
    }
    
    while True:
        try:
            print("\nWaiting for card...")
            result = val.process()
            icon = status_icons.get(result["status"], "❓")
            print(f"{icon} — {result['message']}")
        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"Unexpected System Error: {e}")
        time.sleep(2)


if __name__ == "__main__":
    run_cli()
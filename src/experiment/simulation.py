"""Hardware-free simulation to validate CardSafety end-to-end."""

import glob
import os
import sys
import tempfile
import time
import types

CORE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "core"))
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

try:
    import validator
except ImportError:
    # Allow running without pyscard/pycryptodome; read_card/write_card are mocked below.
    utils_stub = types.ModuleType("utils")
    utils_stub.read_card = lambda: None
    utils_stub.write_card = lambda balance, counter: None
    sys.modules["utils"] = utils_stub
    import validator

import backend


class VirtualCard:
    def __init__(self, uid, balance, counter=0):
        self.uid = uid
        self.balance = balance
        self.counter = counter

    def dump(self):
        return (self.uid, self.balance, self.counter)

    def restore(self, saved_dump):
        self.uid, self.balance, self.counter = saved_dump

    def clone(self):
        return VirtualCard(self.uid, self.balance, self.counter)


_current_card = None


def _mock_read_card():
    if _current_card is None:
        raise RuntimeError("No card present")
    return _current_card.uid, _current_card.balance, _current_card.counter


def _mock_write_card(balance, counter):
    if _current_card is None:
        raise RuntimeError("No card present")
    _current_card.balance = balance
    _current_card.counter = counter


validator.read_card = _mock_read_card
validator.write_card = _mock_write_card


def tap(val, card):
    global _current_card
    _current_card = card
    res = val.process()
    _current_card = None
    time.sleep(0.02)
    return res


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    with tempfile.TemporaryDirectory() as tmp:
        # 1. Baseline vulnerable vs Layer 1 single-validator prevention
        print("=== 1. Single-Validator Replay Prevention ===")
        card = VirtualCard("04a1b2c3", balance=10)
        saved_dump = card.dump()

        bus_legacy = validator.Validator("bus_legacy", security_enabled=False)
        r1 = tap(bus_legacy, card)
        card.restore(saved_dump)
        r2 = tap(bus_legacy, card)
        print(f"Legacy (sec=OFF) tap 1:         {r1['status']} -> {r1['message']}")
        print(f"Legacy (sec=OFF) after restore: {r2['status']} -> {r2['message']}  (attack succeeds)")
        assert r1["status"] == "ok" and r2["status"] == "ok"

        card.restore(saved_dump)
        bus_1 = validator.Validator("bus_1", ledger_file=os.path.join(tmp, "ledger_bus_1.log"))
        r3 = tap(bus_1, card)
        card.restore(saved_dump)
        r4 = tap(bus_1, card)
        print(f"Protected (sec=ON) tap 1:       {r3['status']} -> {r3['message']}")
        print(f"Protected (sec=ON) after dump:  {r4['status']} -> {r4['message']}  (blocked)")
        assert r3["status"] == "ok" and r4["status"] == "replay"

        # Legitimate remaining ride -> insufficient balance check
        card_low = VirtualCard("04a1b2c4", balance=7)
        r_ok = tap(bus_1, card_low)
        r_insuf = tap(bus_1, card_low)
        print(f"Insufficient balance check:     {r_ok['status']} then {r_insuf['status']} -> {r_insuf['message']}")
        assert r_ok["status"] == "ok" and r_insuf["status"] == "insufficient"

        # 2. Cross-validator clone attack in the same offline session
        print("\n=== 2. Cross-Validator Clone (Offline Intra-Session) ===")
        bus_2 = validator.Validator("bus_2", ledger_file=os.path.join(tmp, "ledger_bus_2.log"))

        legit = VirtualCard("04cafe01", balance=20)
        tap(bus_1, legit)
        tap(bus_2, legit)
        print(f"Legit card {legit.uid}: bus_1 -> bus_2 (balance={legit.balance}, counter={legit.counter})")

        orig = VirtualCard("04deadbe", balance=20)
        clone_dump = orig.dump()
        clone = orig.clone()

        c1 = tap(bus_1, orig)
        c2 = tap(bus_2, clone)
        c3 = tap(bus_1, orig)
        c4 = tap(bus_2, clone)
        print(f"Original on bus_1: {c1['status']}, {c3['status']}")
        print(f"Clone    on bus_2: {c2['status']}, {c4['status']}  (accepted offline before sync)")
        assert all(r["status"] == "ok" for r in (c1, c2, c3, c4))

        # 3. Layer 2 centralized backend anomaly detection
        print("\n=== 3. Backend Anomaly Detection ===")
        backend.LOG_FILES = sorted(glob.glob(os.path.join(tmp, "ledger_*.log")))
        events = backend.load_logs()
        backend.detect_anomalies(events)

        # 4. Synced ledger blocks old clones on other validators in next session
        print("\n=== 4. Post-Sync Protection (Session 2) ===")
        consolidated = os.path.join(tmp, "consolidated.log")
        with open(consolidated, "w") as out_f:
            for path in backend.LOG_FILES:
                with open(path, "r") as in_f:
                    out_f.write(in_f.read())

        bus_3 = validator.Validator("bus_3", ledger_file=consolidated)
        clone.restore(clone_dump)
        r_sync = tap(bus_3, clone)
        print(f"Old clone dump on bus_3 after sync: {r_sync['status']} -> {r_sync['message']}")
        assert r_sync["status"] == "replay"

        print("\nSimulation finished: all checks passed.")


if __name__ == "__main__":
    main()

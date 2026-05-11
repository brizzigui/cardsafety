import os
import time
import json
import statistics
import random
import sys
import threading

try:
    import psutil
except ImportError:
    psutil = None

from validator import Validator, FARE
import graphs

# Experimental configurations: (name, security_enabled, history_size)
CONFIGS = [
    ("C1", False, 0),
    ("C2", True, 1000),
    ("C3", True, 10000),
    ("C4", True, 100000),
    ("C5", True, 1000000),
]

TRIALS = 100
RETAP_TIMEOUT = 10  # seconds

VALID_STATUSES = {"ok", "replay", "insufficient", "error"}


def populate_ledger(ledger_file, entries):
    """Generates mock entries to stress-test memory initialization."""
    if entries <= 0:
        if os.path.exists(ledger_file):
            os.remove(ledger_file)
        return

    print(f"Generating {entries} mock entries for {ledger_file} (please wait)...")
    uid_count = min(10000, max(1, entries // 10))
    uids = [f"uid_{i:08x}" for i in range(uid_count)]
    counters = {u: random.randint(0, 1000) for u in uids}

    with open(ledger_file, "w") as f:
        for i in range(entries):
            u = uids[i % uid_count]
            counters[u] += 1
            entry = {
                "machine": "seed",
                "uid": u,
                "balance": random.randint(0, 10000),
                "counter": counters[u],
                "operation": -FARE,
                "timestamp": time.time() - random.randint(0, 86400),
            }
            f.write(json.dumps(entry) + "\n")


def run_single_attempt(val_instance):
    """Executes a single processing attempt against the active validator object."""
    start = time.perf_counter()
    result = val_instance.process()
    elapsed = (time.perf_counter() - start) * 1000.0

    if psutil:
        mem = psutil.Process(os.getpid()).memory_info().rss / 1024.0 / 1024.0
    else:
        mem = -1.0

    status = result.get("status", "error")
    if status not in VALID_STATUSES:
        status = "error"

    return status, elapsed, mem, result.get("message", "")


def input_with_timeout(prompt, timeout):
    """Helper to prompt the user to retap, allowing timeout auto-skip."""
    print(prompt, end="", flush=True)
    result = [None]

    def _read():
        try:
            result[0] = sys.stdin.readline()
        except Exception:
            pass

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        print("")
        return None
    return result[0].rstrip("\n") if result[0] is not None else None


def run_experiment(out_dir="./experiment_results"):
    os.makedirs(out_dir, exist_ok=True)
    results = []

    for name, enabled, history in CONFIGS:
        print(f"\n=== Running {name}: Security={'ON' if enabled else 'OFF'}, History={history} ===")
        machine_name = f"exp_{name}"
        ledger_file = f"ledger_{machine_name}.log"

        # 1. Prepare environment data
        if enabled:
            populate_ledger(ledger_file, history)
        else:
            if os.path.exists(ledger_file):
                os.remove(ledger_file)

        # 2. Instantiate Validator cleanly (Handles its own ONE-TIME load)
        val = Validator(machine_name=machine_name, ledger_file=ledger_file, security_enabled=enabled)

        times = []
        mems = []
        statuses = {s: 0 for s in VALID_STATUSES}

        print(f"\nPlease perform {TRIALS} physical taps for {name}.")
        print("Press Ctrl+C anytime to abort early.\n")

        attempts_done = 0
        try:
            while attempts_done < TRIALS:
                print(f"Tap {attempts_done + 1}/{TRIALS} — present card now")
                status, elapsed, mem, message = run_single_attempt(val)

                if status == "error":
                    print(f"  -> ignored error (bad read/no card): {message}")
                    time.sleep(1) # Prevent endless loop spamming when no card is present
                    continue

                times.append(elapsed)
                mems.append(mem)
                statuses[status] += 1
                attempts_done += 1
                
                print(f"  -> {status}, {elapsed:.1f} ms, mem={mem:.1f} MB")

                if attempts_done < TRIALS:
                    input_with_timeout(
                        f"  Remove card and re-present, then press Enter (or wait {RETAP_TIMEOUT}s to continue): ",
                        RETAP_TIMEOUT
                    )
        except KeyboardInterrupt:
            print("\nExperiment aborted by user — saving partial results.")

        avg_time = statistics.mean(times) if times else 0.0
        avg_mem = statistics.mean([m for m in mems if m >= 0]) if mems and any(m >= 0 for m in mems) else -1.0

        res = {
            "config": name,
            "security_enabled": enabled,
            "history_size": history,
            "attempts": len(times),
            "avg_time_ms": avg_time,
            "avg_mem_mb": avg_mem,
            "statuses": statuses,
        }
        results.append(res)

        with open(os.path.join(out_dir, f"results_{name}.json"), "w") as f:
            json.dump({"meta": res, "times": times, "mems": mems}, f, indent=2)

    # Compile Summary
    summary_file = os.path.join(out_dir, "summary.json")
    with open(summary_file, "w") as f:
        json.dump(results, f, indent=2)

    try:
        graphs.plot_results(results, out_path=os.path.join(out_dir, "experiment_plot.png"))
    except Exception as e:
        print("\nFailed to plot results:", e)

    print(f"\nExperiment finished. Results saved to {out_dir}")


if __name__ == "__main__":
    run_experiment()
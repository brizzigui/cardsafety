import os
import time
import json
import statistics
import random
import sys
import threading

try:
    import psutil
except Exception:
    psutil = None

import validator
import graphs

# Experimental configurations (name, security_enabled, history_size)
CONFIGS = [
    ("C1", False, 0),
    ("C2", True, 1000),
    ("C3", True, 10000),
    ("C4", True, 100000),
    ("C5", True, 1000000),
]

TRIALS = 100
RETAP_TIMEOUT = 10  # seconds to allow user to remove and re-present the card

VALID_STATUSES = {"ok", "replay", "insufficient", "error"}


def populate_ledger(ledger_file, entries):
    """Populate `ledger_file` with mock entries (JSON lines) for stress testing."""
    if entries <= 0:
        try:
            if os.path.exists(ledger_file):
                os.remove(ledger_file)
        except Exception:
            pass
        return

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
                "operation": -validator.FARE,
                "timestamp": time.time() - random.randint(0, 86400),
            }
            f.write(json.dumps(entry) + "\n")


def run_single_attempt():
    """Run one validator.process() call and return structured timing + result.

    Returns a tuple: (status, elapsed_ms, memory_mb, message)
      - status:     one of "ok", "replay", "insufficient", "error"
      - elapsed_ms: wall-clock time of the process() call in milliseconds
      - memory_mb:  RSS memory of this process after the call (-1 if unavailable)
      - message:    human-readable detail from the validator
    """
    start = time.perf_counter()
    result = validator.process()
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
    """Print `prompt` and wait up to `timeout` seconds for a newline."""
    print(prompt, end="", flush=True)
    result = [None]

    def _read():
        try:
            result[0] = sys.stdin.readline()
        except Exception:
            result[0] = None

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

    # keep originals to restore after monkey-patching
    orig_state_seen = getattr(validator, "state_seen", None)
    orig_log_state = getattr(validator, "log_state", None)

    try:
        for name, enabled, history in CONFIGS:
            print(
                f"\n=== Running {name}: "
                f"security={'ENABLED' if enabled else 'DISABLED'}, "
                f"history={history} ==="
            )

            validator.MACHINE_NAME = f"exp_{name}"
            ledger_file = f"ledger_{validator.MACHINE_NAME}.log"

            if not enabled:
                # Disable ledger checks for the baseline config
                validator.LEDGER_FILE = ""
                validator.state_seen = lambda uid, counter: False
                validator.log_state = lambda uid, balance, counter: None
            else:
                validator.LEDGER_FILE = ledger_file
                print(
                    f"Populating ledger {ledger_file} "
                    f"with {history} entries (may take a while)..."
                )
                populate_ledger(ledger_file, history)
                validator.load_ledger()

            times = []
            mems = []
            statuses = {s: 0 for s in VALID_STATUSES}

            print(
                f"Please perform {TRIALS} physical taps for {name}.\n"
                "Press Ctrl+C to abort early."
            )

            attempts_done = 0
            try:
                while attempts_done < TRIALS:
                    print(f"Tap {attempts_done + 1}/{TRIALS} — present card now")
                    status, elapsed, mem, message = run_single_attempt()

                    if status == "error":
                        print(f"  -> error (not counted): {message}")
                    else:
                        times.append(elapsed)
                        mems.append(mem)
                        statuses[status] += 1
                        attempts_done += 1
                        print(f"  -> {status}, {elapsed:.1f} ms, mem={mem:.1f} MB")

                    input_with_timeout(
                        f"  Remove card and re-present, then press Enter "
                        f"(or wait {RETAP_TIMEOUT}s to continue): ",
                        RETAP_TIMEOUT,
                    )
            except KeyboardInterrupt:
                print("Experiment aborted by user — saving partial results.")

            avg_time = statistics.mean(times) if times else 0.0
            avg_mem = (
                statistics.mean([m for m in mems if m >= 0])
                if mems and any(m >= 0 for m in mems)
                else -1.0
            )

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

    finally:
        if orig_state_seen is not None:
            validator.state_seen = orig_state_seen
        if orig_log_state is not None:
            validator.log_state = orig_log_state

    summary_file = os.path.join(out_dir, "summary.json")
    with open(summary_file, "w") as f:
        json.dump(results, f, indent=2)

    try:
        graphs.plot_results(
            results, out_path=os.path.join(out_dir, "experiment_plot.png")
        )
    except Exception as e:
        print("Failed to plot results:", e)

    print("Experiment finished. Results saved to", out_dir)


if __name__ == "__main__":
    run_experiment()
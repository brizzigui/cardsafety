import os
import time
import json
import statistics
import io
import contextlib
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


def populate_ledger(ledger_file, entries):
    """Populate `ledger_file` with mock entries (JSON lines) for stress testing.

    The function writes `entries` JSON lines. UIDs are generated pseudo-randomly
    and counters are monotonically increasing per UID to mimic a real ledger.
    """
    if entries <= 0:
        # ensure file does not exist
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
                "timestamp": time.time() - random.randint(0, 86400)
            }
            f.write(json.dumps(entry) + "\n")


def run_single_attempt():
    """Run a single `validator.process()` call while capturing printed output.

    Returns a tuple: (status_str, elapsed_ms, memory_mb, raw_output)
    """
    buf = io.StringIO()
    start = time.perf_counter()
    try:
        with contextlib.redirect_stdout(buf):
            validator.process()
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000.0
        out = buf.getvalue()
        status = f"error: {e}"
    else:
        elapsed = (time.perf_counter() - start) * 1000.0
        out = buf.getvalue()
        if "✅ OK" in out:
            status = "ok"
        elif "🚫 Replay detected" in out:
            status = "replay"
        elif "🚫 Insufficient balance" in out:
            status = "insufficient"
        else:
            status = "unknown"

    if psutil:
        mem = psutil.Process(os.getpid()).memory_info().rss / 1024.0 / 1024.0
    else:
        mem = -1.0

    return status, elapsed, mem, out


def run_experiment(out_dir="./experiment_results"):
    os.makedirs(out_dir, exist_ok=True)

    results = []

    # keep originals to restore later
    orig_state_seen = getattr(validator, "state_seen", None)
    orig_log_state = getattr(validator, "log_state", None)

    try:
        for name, enabled, history in CONFIGS:
            print(f"\n=== Running {name}: security={'ENABLED' if enabled else 'DISABLED'}, history={history} ===")

            # Prepare machine/ledger
            validator.MACHINE_NAME = f"exp_{name}"
            ledger_file = f"ledger_{validator.MACHINE_NAME}.log"

            if not enabled:
                # disable ledger checks and logging by monkey-patching
                validator.LEDGER_FILE = ""
                validator.state_seen = lambda uid, counter: False
                validator.log_state = lambda uid, balance, counter: None
            else:
                validator.LEDGER_FILE = ledger_file
                # populate ledger with 'history' lines
                print(f"Populating ledger {ledger_file} with {history} entries (may take a while)...")
                populate_ledger(ledger_file, history)
                # reload into memory
                validator.load_ledger()

            # Run TRIALS attempts; user will physically tap card for each attempt.
            times = []
            mems = []
            statuses = {"ok": 0, "replay": 0, "insufficient": 0, "unknown": 0}

            print(f"Please perform {TRIALS} physical taps for {name}.\nPress Ctrl+C to abort early.")

            def input_with_timeout(prompt, timeout):
                print(prompt, end="", flush=True)
                result = [None]

                def target():
                    try:
                        # use readline to avoid leftover prompt issues
                        result[0] = sys.stdin.readline()
                    except Exception:
                        result[0] = None

                t = threading.Thread(target=target)
                t.daemon = True
                t.start()
                t.join(timeout)
                if t.is_alive():
                    print("")
                    return None
                return result[0].rstrip("\n") if result[0] is not None else None

            # Loop until we have TRIALS successful (non-error) attempts recorded
            attempts_done = 0
            try:
                while attempts_done < TRIALS:
                    print(f"Tap {attempts_done+1}/{TRIALS} — present card now")
                    status, elapsed, mem, out = run_single_attempt()

                    if isinstance(status, str) and status.startswith("error"):
                        # do not count errors as taps
                        print(f"  -> error (not counted): {status}")
                    else:
                        times.append(elapsed)
                        mems.append(mem)
                        short = status.split(":")[0]
                        if short in statuses:
                            statuses[short] += 1
                        else:
                            statuses["unknown"] += 1
                        attempts_done += 1
                        print(f"  -> {short}, {elapsed:.1f} ms, mem={mem:.1f} MB")

                    # allow user to remove and re-present the card
                    input_with_timeout(f"  Remove card and re-present, then press Enter (or wait {RETAP_TIMEOUT}s to continue): ", RETAP_TIMEOUT)
            except KeyboardInterrupt:
                print("Experiment aborted by user — saving partial results.")

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

            # save per-config raw results
            with open(os.path.join(out_dir, f"results_{name}.json"), "w") as f:
                json.dump({"meta": res, "times": times, "mems": mems}, f, indent=2)

    finally:
        # restore originals
        if orig_state_seen is not None:
            validator.state_seen = orig_state_seen
        if orig_log_state is not None:
            validator.log_state = orig_log_state

    # write summary and plot
    summary_file = os.path.join(out_dir, "summary.json")
    with open(summary_file, "w") as f:
        json.dump(results, f, indent=2)

    try:
        graphs.plot_results(results, out_path=os.path.join(out_dir, "experiment_plot.png"))
    except Exception as e:
        print("Failed to plot results:", e)

    print("Experiment finished. Results saved to", out_dir)


if __name__ == "__main__":
    run_experiment()

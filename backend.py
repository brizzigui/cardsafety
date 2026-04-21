import json
import glob
from collections import defaultdict

LOG_FILES = glob.glob("*.log")


def load_logs():
    events = []
    for file in LOG_FILES:
        with open(file, "r") as f:
            for line in f:
                e = json.loads(line)
                e["source_file"] = file
                events.append(e)
    return events


def group_by_uid(events):
    by_uid = defaultdict(list)
    for e in events:
        by_uid[e["uid"]].append(e)
    return by_uid


def expected_next_state(e):
    new_balance = e["balance"] + e["operation"]
    new_counter = e["counter"] + 1
    return (new_balance, new_counter)


def detect_anomalies(events):
    by_uid = group_by_uid(events)

    for uid, logs in by_uid.items():
        print(f"\n=== Card {uid} ===")

        logs.sort(key=lambda x: x["timestamp"])

        seen_states = set()
        transitions = {}

        for e in logs:
            state = (e["balance"], e["counter"])

            # --- replay detection ---
            if state in seen_states:
                print("⚠️ Replay detected:", state, "at", e["machine"])
            seen_states.add(state)

            next_state = expected_next_state(e)

            # --- fork detection ---
            if state in transitions:
                if transitions[state] != next_state:
                    print("⚠️ Fork detected:")
                    print("   from:", state)
                    print("   to:", transitions[state], "and", next_state)
            else:
                transitions[state] = next_state

        # --- temporal / inter-machine anomaly ---
        for i in range(len(logs) - 1):
            a = logs[i]
            b = logs[i + 1]

            state_a = (a["balance"], a["counter"])
            expected_a = expected_next_state(a)
            state_b = (b["balance"], b["counter"])

            # same state used in different machines
            if state_a == state_b and a["machine"] != b["machine"]:
                print("⚠️ Possible clone (same state, different machines):")
                print("   ", a)
                print("   ", b)

            # impossible transition (break in chain)
            if expected_a != state_b:
                print("⚠️ Broken transition:")
                print("   expected:", expected_a)
                print("   got     :", state_b)
                print("   between:")
                print("   ", a)
                print("   ", b)


if __name__ == "__main__":
    events = load_logs()
    detect_anomalies(events)
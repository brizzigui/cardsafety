import time
from utils import read_card, write_card

def create(balance):
    try:
        uid, b, c = read_card()
        print(f"⚠️ Already initialized → {b}, {c}")
        if input("Overwrite? (y/N): ").lower() != "y":
            return
    except:
        print("Blank card detected")

    write_card(balance, 0)
    print(f"✅ Created with balance={balance}")


if __name__ == "__main__":
    while True:
        val = input("Initial balance (q to quit): ")
        if val == "q":
            break

        print("Place card...")
        time.sleep(1)

        create(int(val))
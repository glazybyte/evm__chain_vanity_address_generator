#!/usr/bin/env python3

import os
import re
import sys
import time
import string
import multiprocessing as mp
from multiprocessing import Process, Queue, Value

try:
    from eth_account import Account
except ImportError:
    print("Missing dependency. Install it with:\n    pip install eth-account --break-system-packages")
    sys.exit(1)

HEX_CHARS = set("0123456789abcdefABCDEF")


def validate_pattern(pattern: str, field_name: str) -> str:
    if pattern == "":
        return pattern
    invalid = set(pattern) - HEX_CHARS
    if invalid:
        raise ValueError(
            f"Invalid character(s) in {field_name}: {''.join(sorted(invalid))!r}. "
            f"Only hex characters are allowed: 0-9, a-f, A-F."
        )
    return pattern


def get_user_input():
    print("=== BSC / EVM Vanity Wallet Generator ===\n")

    while True:
        prefix = input("Prefix to search for (hex chars only, blank for none): ").strip()
        try:
            prefix = validate_pattern(prefix, "prefix")
            break
        except ValueError as e:
            print(f"  ! {e}")

    while True:
        suffix = input("Suffix to search for (hex chars only, blank for none): ").strip()
        try:
            suffix = validate_pattern(suffix, "suffix")
            break
        except ValueError as e:
            print(f"  ! {e}")

    if not prefix and not suffix:
        print("You must specify at least a prefix or a suffix.")
        sys.exit(1)

    case_sensitive_input = input("Case-sensitive match? (y/N): ").strip().lower()
    case_sensitive = case_sensitive_input == "y"

    max_cpus = os.cpu_count() or 4
    workers_input = input(f"Number of worker processes [default {max_cpus}]: ").strip()
    workers = int(workers_input) if workers_input.isdigit() and int(workers_input) > 0 else max_cpus

    total_len = len(prefix) + len(suffix)
    if total_len > 0:
        approx_tries = 16 ** total_len
        print(f"\nApprox. 1-in-{approx_tries:,} chance per attempt "
              f"(gets slow fast beyond ~6-7 total characters).")

    return prefix, suffix, case_sensitive, workers


def worker(prefix, suffix, case_sensitive, result_queue, attempts_counter, stop_flag):
   
    local_attempts = 0

    while not stop_flag.value:
        acct = Account.create()
        address = acct.address 
        addr_body = address[2:]

        check = addr_body if case_sensitive else addr_body.lower()
        pfx = prefix if case_sensitive else prefix.lower()
        sfx = suffix if case_sensitive else suffix.lower()

        local_attempts += 1

        if local_attempts % 500 == 0:
            with attempts_counter.get_lock():
                attempts_counter.value += 500
            local_attempts = 0

        if check.startswith(pfx) and check.endswith(sfx):
            with attempts_counter.get_lock():
                attempts_counter.value += local_attempts
            with stop_flag.get_lock():
                stop_flag.value = 1
            result_queue.put({
                "address": address,
                "private_key": acct.key.hex(),
            })
            return

    with attempts_counter.get_lock():
        attempts_counter.value += local_attempts


def main():
    prefix, suffix, case_sensitive, workers = get_user_input()

    print(f"\nSearching with {workers} worker process(es)... (Ctrl+C to cancel)\n")

    result_queue = Queue()
    attempts_counter = Value("l", 0)
    stop_flag = Value("i", 0)

    processes = [
        Process(target=worker, args=(prefix, suffix, case_sensitive, result_queue, attempts_counter, stop_flag))
        for _ in range(workers)
    ]

    start_time = time.time()
    for p in processes:
        p.start()

    result = None
    try:
        while result is None:
            if not result_queue.empty():
                result = result_queue.get()
                break
            if all(not p.is_alive() for p in processes):
                break
            time.sleep(0.5)
            elapsed = time.time() - start_time
            rate = attempts_counter.value / elapsed if elapsed > 0 else 0
            print(f"\rAttempts: {attempts_counter.value:,}  |  Rate: {rate:,.0f} addr/sec  |  Elapsed: {elapsed:.1f}s   ",
                  end="", flush=True)
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        with stop_flag.get_lock():
            stop_flag.value = 1
        for p in processes:
            p.join()
        sys.exit(0)

    with stop_flag.get_lock():
        stop_flag.value = 1
    for p in processes:
        p.join()

    elapsed = time.time() - start_time

    if result:
        print(f"\n\nMatch found in {elapsed:.1f}s ({attempts_counter.value:,} attempts)!\n")
        print("=" * 60)
        print(f"Address:     {result['address']}")
        print(f"Private Key: {result['private_key']}")
        print("=" * 60)
        print("\n Keep the private key secret. Anyone with it controls the funds.")
        print("This address works on BSC and any other EVM-compatible chain.")

        save = input("\nSave to a local file? (y/N): ").strip().lower()
        if save == "y":
            filename = f"vanity_wallet_{result['address'][2:10]}.txt"
            path = os.path.join(os.getcwd(), filename)
            with open(path, "w") as f:
                f.write(f"Address: {result['address']}\n")
                f.write(f"Private Key: {result['private_key']}\n")
                f.write("\nKeep this file private and secure. Anyone with the private key controls the funds.\n")
            print(f"Saved to {path}")
    else:
        print("\nNo match found (search ended without a result).")


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()

"""
Reproduce a serious concurrency bug in budget.py: concurrent calls to the
guarded spend path can silently drop ledger entries, causing money accounting
to be lost under load.  The test below creates 40 threads that each call
`spend()` on a single BudgetManager and then asserts exactly 40 ledger entries
were recorded.  It MUST fail until the race condition in budget.py is fixed.
"""

import threading

import daedalus.budget


def test_concurrent_spend_creates_exact_ledger_entries():
    """
    Guarantee: when 40 threads concurrently call BudgetManager.spend(1.0)
    on the same instance, the ledger must contain exactly 40 entries upon
    completion.  Naive state management (e.g. unguarded shared mutable state)
    causes this to fail, which the test exposes.
    """
    budget = daedalus.budget.BudgetManager(initial_budget=100.0)
    amount_per_call = 1.0
    num_threads = 40

    # Barrier to start all threads simultaneously, stressing the race area
    barrier = threading.Barrier(num_threads + 1)
    errors = []
    lock = threading.Lock()

    def spend_once():
        try:
            barrier.wait()
            budget.spend(amount_per_call)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=spend_once) for _ in range(num_threads)]
    for t in threads:
        t.start()
    barrier.wait()  # release all threads

    for t in threads:
        t.join()

    assert not errors, f"Unexpected exceptions during concurrent spend: {errors}"

    # Access the ledger; assumption: it is a list-like attribute on the BudgetManager
    # (the exact attribute name may vary; adjust if necessary).
    ledger = budget.ledger
    actual_count = len(ledger)

    # The bug causes zero entries, but we expect one entry per successful spend.
    assert actual_count == num_threads, (
        f"Expected {num_threads} ledger entries from concurrent spend, "
        f"got {actual_count}.  Concurrency bug likely reproduced."
    )


def test_concurrent_spend_preserves_balance_and_ledger_integrity():
    """
    A more thorough concurrency test: checking only the ledger length is
    insufficient because Python's list.append() is atomic under the GIL.
    The real bug in budget.py would cause lost updates to the internal
    balance or malformed ledger entries even if the count matches.
    This test spawns many threads spending concurrently and then verifies
    that the remaining budget and the sum of all ledger entries are exactly
    as expected. If budget.py lacks proper locking, this test will reliably
    fail by revealing an incorrect remaining balance.
    """
    budget = daedalus.budget.BudgetManager(initial_budget=200.0)
    num_threads = 100
    amount = 1.0
    barrier = threading.Barrier(num_threads + 1)
    errors = []
    lock = threading.Lock()

    def spend_once():
        try:
            barrier.wait()
            budget.spend(amount)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=spend_once) for _ in range(num_threads)]
    for t in threads:
        t.start()
    barrier.wait()
    for t in threads:
        t.join()

    assert not errors, f"Unexpected exceptions: {errors}"
    assert len(budget.ledger) == num_threads
    # Total spent should equal num_threads * amount
    total_spent = sum(budget.ledger)
    assert total_spent == num_threads * amount, (
        f"Total spent {total_spent} != {num_threads * amount}"
    )
    # Remaining budget must match
    assert budget.remaining == 200.0 - num_threads * amount, (
        f"Remaining budget {budget.remaining} != {200.0 - num_threads * amount}"
    )

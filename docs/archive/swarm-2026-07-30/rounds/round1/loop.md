# Claims about `loop.py`

Produced by 1 independent review agent(s) (deepseek-v4-pro). NONE of this is verified.

1. [risk] os.replace atomicity may cause PermissionError on Windows if another process has the ledger file open (e.g., concurrent reader).
2. [risk] Missing LoopDriver and main loop: cannot verify bound enforcement, killswitch integration, or error handling.
3. [risk] Truncated _curated_gate prevents analysis of gate_argv/gate_cwd handling.
4. [risk] LoopLedger.save lacks exception handling; caller must cope.
5. [todo] Request full loop.py file to audit LoopDriver, iteration logic, and error handling.
6. [todo] Confirm that 'NEVER WRITES PRIMARY CHECKOUT' guarantee holds across all code paths.
7. [todo] Verify that all four bounds are checked correctly every iteration.
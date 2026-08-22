# Gate-0 v3 Blocker Classification (406 write-surfaces)

## Top 20 Files by Surface Count

| File | Surfaces | Top 3 Kinds | Door(s) | Closure |
|------|----------|-------------|---------|---------|
| daedalus/kernel/source_trees.py | 18 | os.open:3, target.parent.mkdir:2, stream.write:2 | NO DOOR | register-row or dead-code |
| daedalus/file_bridge.py | 17 | OUTBOX.mkdir:3, ARCHIVE.mkdir:2, os.replace:2 | file_bridge.watch, +3 | declare-under-file_bridge.watch |
| daedalus/eval/correctness.py | 16 | subprocess.run:4, open:3, fh.write:2 | cli.eval_correctness | declare-under-cli.eval_correctness |
| daedalus/kernel/promotion_trust_root.py | 14 | fh.write:4, open:3, path.parent.mkdir:2 | NO DOOR | register-row or dead-code |
| daedalus/kairos/worktree.py | 13 | os.unlink:4, os.rmdir:3, worktree_path.parent.mkdir:1 | worktree.commit, +3 | declare-under-worktree.commit |
| daedalus/atomic.py | 11 | target.parent.mkdir:3, tmp.write_text:1, tmp.write_bytes:1 | NO DOOR | register-row or dead-code |
| daedalus/web_api.py | 9 | self.wfile.write:8, run:1 | cli.web_api, +3 | declare-under-cli.web_api |
| daedalus/core.py | 8 | subprocess.run:2, provider.run:1, platform.system:1 | NO DOOR | register-row or dead-code |
| daedalus/eval/graph_delta.py | 8 | out.parent.mkdir:3, out.write_text:3, run:1 | cli.eval_graph_delta | declare-under-cli.eval_graph_delta |
| daedalus/runtimes/provider_observation_store.py | 8 | os.open:2, temporary.unlink:2, sqlite3.connect:1 | NO DOOR | register-row or dead-code |
| daedalus/providers/ollama.py | 7 | target.parent.mkdir:2, target.write_text:2, subprocess.run:2 | provider.ollama.rollback, +1 | declare-under-provider.ollama.rollback |
| daedalus/runtimes/container_fault_driver.py | 7 | tempfile.mkdtemp:1, shutil.rmtree:1, tempfile.mkstemp:1 | runtimes.container_fault_driver | declare-under-runtimes.container_fault_driver |
| daedalus/runtimes/live_probe_drivers.py | 7 | target.open:1, platform.system:1, tempfile.mkdtemp:1 | NO DOOR | register-row or dead-code |
| daedalus/selftest.py | 7 | <expression>.write_text:2, run:1, tempfile.mkdtemp:1 | cli.selftest | declare-under-cli.selftest |
| daedalus/bookkeeper.py | 6 | <expression>.write_text:3, subprocess.run:1, ARTIFACT.write_text:1 | cli.bookkeeper | declare-under-cli.bookkeeper |
| daedalus/budget.py | 6 | self.path.parent.mkdir:2, open:1, tmp.write_text:1 | NO DOOR | register-row or dead-code |
| daedalus/council/bus.py | 6 | store_path.open:2, ap.open:1, json.dump:1 | NO DOOR | register-row or dead-code |
| daedalus/council/vendors.py | 6 | open:3, tempfile.TemporaryDirectory:2, in_path.write_text:1 | NO DOOR | register-row or dead-code |
| daedalus/eval/harness.py | 6 | open:4, json.dump:1, fh.write:1 | NO DOOR | register-row or dead-code |
| daedalus/eval/mint.py | 6 | open:3, subprocess.run:1, json.dump:1 | NO DOOR | register-row or dead-code |

## Summary

**Total files with write failures:** 108
**Files with door (37):** 171 surfaces
**Files with NO DOOR (71):** 235 surfaces

**Closable by declaration:** 171 / 406
**Requiring register/dead-code:** 235 / 406

## Inventory-Only (8)
- provider.claude
- provider.codex
- provider.deepseek
- provider.deepseek.rollback
- provider.ollama.rollback
- provider.ollama_native
- runs.gate0_matrix.verify_whole_matrix
- runtimes.fault_attestation_issuer
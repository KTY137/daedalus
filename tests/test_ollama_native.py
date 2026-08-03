"""Tests for the native Ollama /api/chat client and the context-window fail-loud
rules it enables in the OllamaProvider.

Everything is offline: a stdlib http.server on an ephemeral port stands in for
Ollama, records every request body, and returns scripted native responses. No
network, no real model. The window math uses ``daedalus.structcore.tokens``
(cl100k when tiktoken is present); the thresholds here keep wide margins so the
outcome is the same under the chars/4 fallback.
"""

import json
import os
import socket
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from daedalus.providers._ollama_native import (
    DEFAULT_NUM_CTX,
    OUTPUT_RESERVE_TOKENS,
    effective_input_window,
    native_chat,
    num_ctx_value,
)
from daedalus.providers._openai_compat import ProviderHTTPError
from daedalus.providers.ollama import OllamaProvider, _window_replacement_lines

_AGENT = {"name": "docs-dev", "call_name": "Lucia"}


def _resp(content, tool_calls=None):
    """Build a native /api/chat non-stream response dict."""
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"message": message, "done": True, "done_reason": "stop"}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {"_raw": raw.decode("utf-8", "replace")}
        self.server.requests.append(body)
        status, payload = self.server.take()
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # keep the test output clean
        pass


class FakeOllama:
    """Context manager: an ephemeral-port native endpoint that records request
    bodies (``.requests``) and returns ``responses`` (list of ``(status, dict)``)
    in order, defaulting to an empty report once exhausted."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def __enter__(self):
        srv = HTTPServer(("127.0.0.1", 0), _Handler)
        srv.requests = self.requests
        srv._responses = self._responses
        srv._i = 0

        def take():
            i = srv._i
            srv._i += 1
            if i < len(srv._responses):
                return srv._responses[i]
            return (200, _resp("{}"))

        srv.take = take
        self._srv = srv
        self._thread = threading.Thread(target=srv.serve_forever, daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{srv.server_address[1]}"
        return self

    def __exit__(self, *exc):
        self._srv.shutdown()
        self._srv.server_close()


def _provider(url):
    p = OllamaProvider()
    p.host = url
    return p


# --------------------------------------------------------------------------- #
# native_chat request body / options                                          #
# --------------------------------------------------------------------------- #
class NativeChatBodyTests(unittest.TestCase):
    def test_default_num_ctx_and_temperature_in_options(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OLLAMA_NUM_CTX", None)
            with FakeOllama([(200, _resp("ok"))]) as srv:
                native_chat(host=srv.url, model="m",
                            messages=[{"role": "user", "content": "hi"}], temperature=0.3)
            body = srv.requests[0]
        self.assertEqual(body["options"]["num_ctx"], 6144)
        self.assertEqual(body["options"]["temperature"], 0.3)
        self.assertFalse(body["stream"])
        self.assertNotIn("format", body)      # force_json default False
        self.assertNotIn("keep_alive", body)  # not provided
        self.assertNotIn("tools", body)       # not provided

    def test_env_num_ctx_is_honored(self):
        with mock.patch.dict(os.environ, {"OLLAMA_NUM_CTX": "8192"}):
            self.assertEqual(num_ctx_value(), 8192)
            self.assertEqual(effective_input_window(), 8192 - OUTPUT_RESERVE_TOKENS)
            self.assertEqual(effective_input_window(output_reserve=2048), 6144)
            with FakeOllama([(200, _resp("ok"))]) as srv:
                native_chat(host=srv.url, model="m",
                            messages=[{"role": "user", "content": "hi"}])
                self.assertEqual(srv.requests[0]["options"]["num_ctx"], 8192)

    def test_invalid_env_falls_back_to_default(self):
        with mock.patch.dict(os.environ, {"OLLAMA_NUM_CTX": "not-an-int"}):
            self.assertEqual(num_ctx_value(), DEFAULT_NUM_CTX)
            self.assertEqual(
                effective_input_window(), DEFAULT_NUM_CTX - OUTPUT_RESERVE_TOKENS)
            with FakeOllama([(200, _resp("ok"))]) as srv:
                native_chat(host=srv.url, model="m",
                            messages=[{"role": "user", "content": "hi"}])
                self.assertEqual(srv.requests[0]["options"]["num_ctx"], DEFAULT_NUM_CTX)

    def test_env_num_ctx_is_clamped_up(self):
        with mock.patch.dict(os.environ, {"OLLAMA_NUM_CTX": "100"}):
            self.assertEqual(num_ctx_value(), 2048)  # clamp floor
            self.assertEqual(effective_input_window(), 1024)

    def test_explicit_num_ctx_overrides(self):
        with FakeOllama([(200, _resp("ok"))]) as srv:
            native_chat(host=srv.url, model="m",
                        messages=[{"role": "user", "content": "hi"}], num_ctx=12345)
        self.assertEqual(srv.requests[0]["options"]["num_ctx"], 12345)

    def test_force_json_flag_only_when_requested(self):
        with FakeOllama([(200, _resp("{}")), (200, _resp("{}"))]) as srv:
            native_chat(host=srv.url, model="m",
                        messages=[{"role": "user", "content": "x"}], force_json=True)
            native_chat(host=srv.url, model="m",
                        messages=[{"role": "user", "content": "x"}], force_json=False)
        self.assertEqual(srv.requests[0]["format"], "json")
        self.assertNotIn("format", srv.requests[1])

    def test_force_json_true_sends_the_bare_string_never_a_schema(self):
        """Every existing bool caller must stay byte-identical: True means the
        literal string "json", never dict-shaped, even though the isinstance
        check that picks between them lives right next to the schema branch."""
        with FakeOllama([(200, _resp("{}"))]) as srv:
            native_chat(host=srv.url, model="m",
                        messages=[{"role": "user", "content": "x"}], force_json=True)
        self.assertEqual(srv.requests[0]["format"], "json")
        self.assertIsInstance(srv.requests[0]["format"], str)

    def test_force_json_dict_is_sent_as_the_schema_verbatim(self):
        """A dict opts the call into schema-constrained decoding: the whole
        object must reach Ollama's `format` field unchanged, not collapsed to
        the bare "json" string a bool would send."""
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
        with FakeOllama([(200, _resp("{}"))]) as srv:
            native_chat(host=srv.url, model="m",
                        messages=[{"role": "user", "content": "x"}], force_json=schema)
        self.assertEqual(srv.requests[0]["format"], schema)

    def test_force_json_empty_dict_is_falsy_and_sends_no_format_key(self):
        """VERIFIED against the source, not assumed: the outer dispatch is
        `if force_json:` (truthiness), evaluated BEFORE the `isinstance(...,
        dict)` check that picks the schema branch. An empty dict is falsy in
        Python, so it never reaches that branch at all -- no "format" key is
        sent, the same as `force_json=False`. Pinned so a future change from
        `if force_json:` to `if force_json is not None:` is a visible,
        deliberate decision rather than a silent behavior change."""
        with FakeOllama([(200, _resp("{}"))]) as srv:
            native_chat(host=srv.url, model="m",
                        messages=[{"role": "user", "content": "x"}], force_json={})
        self.assertNotIn("format", srv.requests[0])

    def test_keep_alive_and_tools_passthrough(self):
        tools = [{"type": "function", "function": {"name": "x", "parameters": {}}}]
        with FakeOllama([(200, _resp("ok"))]) as srv:
            native_chat(host=srv.url, model="m",
                        messages=[{"role": "user", "content": "x"}],
                        keep_alive="30m", tools=tools)
        self.assertEqual(srv.requests[0]["keep_alive"], "30m")
        self.assertEqual(srv.requests[0]["tools"], tools)


# --------------------------------------------------------------------------- #
# native_chat response adapter                                                #
# --------------------------------------------------------------------------- #
class NativeChatAdapterTests(unittest.TestCase):
    def test_dict_arguments_become_json_string_and_synth_id(self):
        tc = [{"function": {"name": "read_file", "arguments": {"path": "a.py"}}}]
        with FakeOllama([(200, _resp("", tool_calls=tc))]) as srv:
            msg = native_chat(host=srv.url, model="m",
                              messages=[{"role": "user", "content": "x"}])
        self.assertEqual(msg["role"], "assistant")
        calls = msg["tool_calls"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["id"], "call_0")            # synthesized (native has none)
        self.assertEqual(calls[0]["function"]["name"], "read_file")
        # arguments re-serialized to a JSON STRING; round-trips to the dict
        self.assertEqual(calls[0]["function"]["arguments"], json.dumps({"path": "a.py"}))
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"path": "a.py"})

    def test_given_id_is_preserved(self):
        tc = [{"id": "abc", "function": {"name": "x", "arguments": {}}}]
        with FakeOllama([(200, _resp("", tool_calls=tc))]) as srv:
            msg = native_chat(host=srv.url, model="m",
                              messages=[{"role": "user", "content": "x"}])
        self.assertEqual(msg["tool_calls"][0]["id"], "abc")

    def test_no_tool_calls_key_absent(self):
        with FakeOllama([(200, _resp("hello world"))]) as srv:
            msg = native_chat(host=srv.url, model="m",
                              messages=[{"role": "user", "content": "x"}])
        self.assertNotIn("tool_calls", msg)          # callers do .get("tool_calls") or []
        self.assertEqual(msg["content"], "hello world")

    def test_request_normalizes_openai_tool_calls_back_to_native(self):
        # The agentic loop feeds our own adapted output back in for the next
        # round; native /api/chat 400s on string arguments, so native_chat must
        # convert them back to a dict and drop id/type before re-POSTing.
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "call_0", "type": "function",
                             "function": {"name": "read_file",
                                          "arguments": json.dumps({"path": "a.py"})}}]},
            {"role": "tool", "tool_call_id": "call_0", "name": "read_file", "content": "body"},
        ]
        with FakeOllama([(200, _resp("ok"))]) as srv:
            native_chat(host=srv.url, model="m", messages=msgs)
        sent = srv.requests[0]["messages"]
        tc = sent[1]["tool_calls"][0]
        self.assertEqual(tc["function"]["arguments"], {"path": "a.py"})  # dict, not string
        self.assertNotIn("id", tc)
        self.assertNotIn("type", tc)


class NativeChatErrorTests(unittest.TestCase):
    def test_http_error_raises_provider_error(self):
        with FakeOllama([(500, {"error": "boom"})]) as srv:
            with self.assertRaises(ProviderHTTPError):
                native_chat(host=srv.url, model="m",
                            messages=[{"role": "user", "content": "x"}])

    def test_unreachable_host_raises_provider_error(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # nothing listening on this port now
        with self.assertRaises(ProviderHTTPError):
            native_chat(host=f"http://127.0.0.1:{port}", model="m",
                        messages=[{"role": "user", "content": "x"}], timeout_s=2)


# --------------------------------------------------------------------------- #
# _run_rewrite: window skip, slice injection, drop-to-fit                      #
# --------------------------------------------------------------------------- #
class RewriteWindowTests(unittest.TestCase):
    def test_window_splice_requires_exact_line_count(self):
        with self.assertRaisesRegex(ValueError, "exact line count required"):
            _window_replacement_lines(
                ["one\n", "two\n"],
                "one\ntwo\nthree",
                at_eof=False,
            )

    def test_window_rewrite_preserves_mixed_eol_bytes_and_sends_a_schema(self):
        original = b"alpha\r\n`old.symbol` is stale.\nomega\r\n"
        edited_line = "`lane_for_host` is current."
        objective = (
            "Broken references:\n"
            "  line 2: old.symbol  -- pkg.py defines no 'symbol'"
        )
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs").mkdir()
            (root / "docs" / "x.md").write_bytes(original)
            (root / "pkg.py").write_text(
                "# old.symbol was replaced by the shared predicate\n"
                "def lane_for_host(host):\n"
                "    return 'trusted'\n",
                encoding="utf-8",
            )
            response = json.dumps({"content": edited_line})
            with FakeOllama([(200, _resp(response))]) as srv:
                report = _provider(srv.url)._run_rewrite(
                    objective, d, ["docs/x.md"], None, 60, None,
                    rewrite_windows={"docs/x.md": [{"line": 2, "radius": 0}]},
                    allowed_write_paths=["docs/x.md"],
                )
            after = (root / "docs" / "x.md").read_bytes()

        self.assertEqual(report["files_changed"], ["docs/x.md"])
        self.assertEqual(
            after,
            b"alpha\r\n`lane_for_host` is current.\nomega\r\n",
        )
        request = srv.requests[0]
        self.assertIs(request["think"], False)
        self.assertEqual(request["format"]["required"], ["content"])
        prompt = request["messages"][1]["content"]
        self.assertIn("CURRENT CODE CONTEXT FROM pkg.py", prompt)
        self.assertIn("EDITABLE LINES 2-2", prompt)

    def test_invalid_window_output_retries_then_refuses_without_writing(self):
        original = b"alpha\n`old.symbol` is stale.\nomega\n"
        objective = (
            "Broken references:\n"
            "  line 2: old.symbol  -- pkg.py defines no 'symbol'"
        )
        invalid = json.dumps({"content": "first\nsecond"})
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "docs").mkdir()
            target = root / "docs" / "x.md"
            target.write_bytes(original)
            (root / "pkg.py").write_text("# old.symbol\n", encoding="utf-8")
            with FakeOllama([
                    (200, _resp(invalid)),
                    (200, _resp(invalid)),
            ]) as srv:
                report = _provider(srv.url)._run_rewrite(
                    objective, d, ["docs/x.md"], None, 60, None,
                    rewrite_windows={"docs/x.md": [{"line": 2, "radius": 0}]},
                    allowed_write_paths=["docs/x.md"],
                )
            after = target.read_bytes()

        self.assertEqual(after, original)
        self.assertEqual(report["files_changed"], [])
        self.assertIn(
            "exact line count required",
            report["handoff"]["skipped"]["docs/x.md"],
        )
        self.assertEqual(len(srv.requests), 2)

    def test_oversized_file_is_skipped_with_no_http_call(self):
        big = "".join(f"value_{i} = compute({i}, {i * 2})\n" for i in range(300))  # ~ >1k tok
        with mock.patch.dict(os.environ, {"OLLAMA_NUM_CTX": "2048"}):
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "src").mkdir()
                (Path(d) / "src" / "big.py").write_text(big, encoding="utf-8")
                with FakeOllama([]) as srv:  # nothing scripted; must not be called
                    report = _provider(srv.url)._run_rewrite(
                        "Refactor", d, ["src/big.py"], None, 60, None,
                        allowed_write_paths=["src/big.py"])
                    self.assertEqual(len(srv.requests), 0)  # NO model call for the file
        self.assertEqual(report["files_changed"], [])
        self.assertIn("context window", report["handoff"]["skipped"]["src/big.py"])

    def test_slice_injection_between_request_and_file_body(self):
        original = "def add(a, b):\n    return a+b\n"
        edited = "def add(a, b):\n    return a + b\n"
        slice_ctx = "# neighbor: def helper() -> int\n# caller: main() -> add(1, 2)\n"
        obj = "Put spaces around the +"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src" / "calc.py").write_text(original, encoding="utf-8")
            with FakeOllama([(200, _resp(json.dumps({"content": edited})))]) as srv:
                report = _provider(srv.url)._run_rewrite(
                    obj, d, ["src/calc.py"], None, 60, None,
                    {"src/calc.py": slice_ctx},
                    allowed_write_paths=["src/calc.py"])
            user = srv.requests[0]["messages"][1]["content"]
        self.assertEqual(report["files_changed"], ["src/calc.py"])
        expected = (f"Change request:\n{obj}\n\n"
                    "Project context (distilled, read-only -- the neighborhood of this file):\n"
                    f"{slice_ctx}\n\nFILE src/calc.py (current contents):\n{original}")
        # The prompt now carries the structural brief (daedalus.lanes.graph_brief)
        # appended AFTER the file body -- see providers/ollama.py's
        # _full_file_content. Pinned as a prefix rather than full equality so this
        # test does not have to hand-render the brief's exact text; the brief's
        # own module is what pins its format.
        self.assertTrue(user.startswith(expected), user)
        self.assertIn("STRUCTURAL BRIEF", user)
        self.assertLess(user.index(slice_ctx), user.index("FILE src/calc.py"))
        self.assertLess(user.index("FILE src/calc.py"), user.index("STRUCTURAL BRIEF"))

    def test_no_slice_is_byte_identical_to_pre_change_prompt(self):
        original = "def add(a, b):\n    return a+b\n"
        edited = "def add(a, b):\n    return a + b\n"
        obj = "Put spaces around the +"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src" / "calc.py").write_text(original, encoding="utf-8")
            with FakeOllama([(200, _resp(json.dumps({"content": edited})))]) as srv:
                _provider(srv.url)._run_rewrite(
                    obj, d, ["src/calc.py"], None, 60, None,
                    allowed_write_paths=["src/calc.py"])
            user = srv.requests[0]["messages"][1]["content"]
        # Same relaxation as above: byte-identical up through the file body, then
        # the structural brief. The historic invariant this test pins -- that
        # NOT supplying a slice does not somehow inject one -- still holds; it is
        # asserted below via the absence of the slice-context header.
        expected = f"Change request:\n{obj}\n\nFILE src/calc.py (current contents):\n{original}"
        self.assertTrue(user.startswith(expected), user)
        self.assertNotIn("Project context (distilled", user)
        self.assertIn("STRUCTURAL BRIEF", user)
        self.assertIn("def add(a, b)", user)

    def test_slice_dropped_to_fit_but_file_still_processed(self):
        original = "def f():\n    return 1\n"                                   # tiny
        slice_big = "".join(f"neighbor_{i} = symbol({i})\n" for i in range(1200))  # huge
        with mock.patch.dict(os.environ, {"OLLAMA_NUM_CTX": "4096"}):
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "m.py").write_text(original, encoding="utf-8")
                with FakeOllama([(200, _resp(json.dumps({"content": original.replace("1", "2")})))]) as srv:
                    report = _provider(srv.url)._run_rewrite(
                        "change", d, ["m.py"], None, 60, None,
                        {"m.py": slice_big}, allowed_write_paths=["m.py"])
                    self.assertEqual(len(srv.requests), 1)      # one call, made WITHOUT the slice
                    user = srv.requests[0]["messages"][1]["content"]
        self.assertEqual(report["files_changed"], ["m.py"])     # file still processed
        self.assertEqual(report["handoff"]["slice_context_dropped"], ["m.py"])
        self.assertNotIn("neighbor_", user)                     # the slice was shed
        self.assertIn("FILE m.py (current contents):", user)


# --------------------------------------------------------------------------- #
# _run_agentic: pre-flight refusal, mid-loop eviction, slice injection         #
# --------------------------------------------------------------------------- #
class AgenticWindowTests(unittest.TestCase):
    def test_preflight_refuses_oversized_objective_with_no_http(self):
        huge_obj = "Refactor this. " * 1200  # well beyond 4096 less output reserve
        with mock.patch.dict(os.environ, {"OLLAMA_NUM_CTX": "4096"}):
            with tempfile.TemporaryDirectory() as d:
                with FakeOllama([]) as srv:  # must never be called
                    report = _provider(srv.url)._run_agentic(
                        huge_obj, d, [], _AGENT, None, 60, None, False)
                    self.assertEqual(len(srv.requests), 0)
        self.assertEqual(report["status"], "blocked")
        self.assertIn("context window", report["summary"])
        self.assertEqual(report["files_changed"], [])

    def test_preflight_allows_prompt_above_old_half_window(self):
        objective = "Refactor this. " * 600  # ~2.4k: above old half, below 4096-reserve
        final = {"status": "needs_review", "summary": "accepted", "files_changed": [],
                 "tests_run": [], "risks": [], "todos": [], "handoff": {}}
        with mock.patch.dict(os.environ, {"OLLAMA_NUM_CTX": "4096"}):
            with tempfile.TemporaryDirectory() as d:
                with FakeOllama([(200, _resp(json.dumps(final)))]) as srv:
                    report = _provider(srv.url)._run_agentic(
                        objective, d, [], _AGENT, None, 60, None, False)
                    self.assertEqual(len(srv.requests), 1)
        self.assertEqual(report["status"], "needs_review")
        self.assertEqual(report["summary"], "accepted")

    def test_mid_loop_eviction_forces_report_with_trimmed_history(self):
        big = "".join(f"data_row_{i} = load({i})\n" for i in range(2000))  # >> window once read
        final_report = {"status": "needs_review", "summary": "done reading", "files_changed": [],
                        "tests_run": [], "risks": [], "todos": [], "handoff": {}}
        tool_call = [{"function": {"name": "read_file", "arguments": {"path": "big.txt"}}}]
        with mock.patch.dict(os.environ, {"OLLAMA_NUM_CTX": "4096"}):
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "big.txt").write_text(big, encoding="utf-8")
                with FakeOllama([(200, _resp("", tool_calls=tool_call)),
                                 (200, _resp(json.dumps(final_report)))]) as srv:
                    report = _provider(srv.url)._run_agentic(
                        "Summarize big.txt", d, ["big.txt"], _AGENT, None, 60, None, False)
                    self.assertEqual(len(srv.requests), 2)   # round-0 tool call + forced report
                    forced = srv.requests[1]["messages"]
        # the forced call carries EXACTLY the evicted 4-message shape
        self.assertEqual([m["role"] for m in forced], ["system", "user", "tool", "user"])
        self.assertEqual(forced[3]["content"], "Stop using tools. Output the final json report now.")
        self.assertIn("truncated to fit the local context window", forced[2]["content"])
        self.assertEqual(report["status"], "needs_review")
        self.assertEqual(report["summary"], "done reading")
        self.assertEqual(report["files_changed"], [])

    def test_slice_injection_in_initial_user_message(self):
        obj = "Review the module"
        slice_texts = {"b.py": "CTX-B skeletons", "a.py": "CTX-A skeletons"}
        final = {"status": "needs_review", "summary": "reviewed", "files_changed": [],
                 "tests_run": [], "risks": [], "todos": [], "handoff": {}}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src" / "calc.py").write_text("x = 1\n", encoding="utf-8")
            with FakeOllama([(200, _resp(json.dumps(final)))]) as srv:
                _provider(srv.url)._run_agentic(
                    obj, d, ["src/calc.py"], _AGENT, None, 60, None, False, slice_texts)
            first_user = srv.requests[0]["messages"][1]["content"]
        hint = "Candidate paths: src/calc.py"
        block = "CTX-A skeletons\n\nCTX-B skeletons"  # values joined in sorted-key order
        self.assertEqual(
            first_user,
            f"Objective:\n{obj}\n\nDistilled project context (read-only, may be partial):\n{block}\n\n{hint}")

    def test_no_slice_initial_message_is_byte_identical(self):
        obj = "Review the module"
        final = {"status": "needs_review", "summary": "reviewed", "files_changed": [],
                 "tests_run": [], "risks": [], "todos": [], "handoff": {}}
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            (Path(d) / "src" / "calc.py").write_text("x = 1\n", encoding="utf-8")
            with FakeOllama([(200, _resp(json.dumps(final)))]) as srv:
                _provider(srv.url)._run_agentic(
                    obj, d, ["src/calc.py"], _AGENT, None, 60, None, False)
            first_user = srv.requests[0]["messages"][1]["content"]
        self.assertEqual(first_user, f"Objective:\n{obj}\n\nCandidate paths: src/calc.py")


if __name__ == "__main__":
    unittest.main()

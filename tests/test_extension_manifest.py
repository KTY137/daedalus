"""Manifest-consistency checks for the VS Code extension in vscode-agent-env/.

`tests/test_comms.py` already checks that package.json parses, that a fixed
subset of commands appear as *strings* in extension.js, and that the file
parses as JS (`node --check`). None of that proves the manifest is internally
consistent: package.json can declare a command that has no handler (dead menu
item), extension.js can register a command nobody contributed (hidden/unlisted
surface), an activation event can point at a typo'd command id, or `main` can
point at a file that was renamed. This module checks the manifest *against
itself and against the source*, in both directions, using real parsers
(`json.loads` for package.json) wherever one is available.

Only extension.js has no real parser available offline: this environment has
no JS AST package (no acorn/esprima/espree under vscode-agent-env/node_modules)
and the project deliberately has no build/compile step, so adding one just for
a test would violate that constraint. Where source text must be scanned, the
regexes below are anchored to the exact VS Code API call shape
(`vscode.commands.registerCommand("id", ...)`, `cfg().get("key")`, etc.) --
i.e. they parse out the argument of a specific, unambiguous function-call
site, not prose. That is a materially different (and much safer) bet than
matching a sentence in a comment or docstring.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = ROOT / "vscode-agent-env"
PACKAGE_JSON_PATH = EXTENSION_DIR / "package.json"
MAIN_JS_PATH = EXTENSION_DIR / "extension.js"
OPENVSCODE_DOCKERFILE = ROOT / "packaging" / "openvscode" / "Dockerfile"

# --- source regexes -------------------------------------------------------
# Each pattern targets one specific VS Code (or local-helper) API call, not
# free text. See module docstring for why regex is used at all here.
REGISTER_COMMAND_RE = re.compile(r'vscode\.commands\.registerCommand\(\s*[\'"]([\w.]+)[\'"]')
REGISTER_WEBVIEW_RE = re.compile(r'vscode\.window\.registerWebviewViewProvider\(\s*[\'"]([\w.]+)[\'"]')
REGISTER_TREEVIEW_RE = re.compile(r'vscode\.window\.registerTreeDataProvider\(\s*[\'"]([\w.]+)[\'"]')
# vscode.window.createTreeView(viewId, {treeDataProvider, ...}) is the OTHER
# real VS Code API for wiring a tree view's provider -- not a second, weaker
# convention. It registers the provider exactly like registerTreeDataProvider
# does, and additionally returns a TreeView handle (used in extension.js for
# `.visible`-gated live refresh, which registerTreeDataProvider cannot give
# you). A view wired this way is registered, so this must count as one too.
CREATE_TREEVIEW_RE = re.compile(r'vscode\.window\.createTreeView\(\s*[\'"]([\w.]+)[\'"]')
# `cfg()` is this extension's own helper (`function cfg() { return
# vscode.workspace.getConfiguration("daedalus"); }` in extension.js) -- the
# pattern is coupled to that local convention, which is fine for a
# same-repo test.
CFG_GET_RE = re.compile(r'cfg\(\)\.get\(\s*[\'"](\w+)[\'"]')
# VS Code "command:" markdown URIs inside viewsWelcome contents, e.g.
# "[Open Dashboard](command:daedalus.openDashboard)".
COMMAND_URI_RE = re.compile(r'command:([\w.]+)')


def load_manifest(package_json_path=PACKAGE_JSON_PATH):
    return json.loads(package_json_path.read_text(encoding="utf-8"))


def load_source(main_js_path=MAIN_JS_PATH):
    return main_js_path.read_text(encoding="utf-8")


# --- pure helpers over (manifest, source) ---------------------------------
# Kept as free functions (not buried in test methods) so a verification
# script can import them and run the exact same logic against a scratch
# fixture to prove each check actually goes red on a broken manifest.

def declared_commands(manifest):
    return {c["command"] for c in manifest["contributes"]["commands"]}


def registered_commands(source):
    return set(REGISTER_COMMAND_RE.findall(source))


def declared_views(manifest):
    """Return {view_id: type_or_None} for the daedalus activity-bar container."""
    return {v["id"]: v.get("type") for v in manifest["contributes"]["views"]["daedalus"]}


def registered_webview_ids(source):
    return set(REGISTER_WEBVIEW_RE.findall(source))


def registered_treeview_ids(source):
    return set(REGISTER_TREEVIEW_RE.findall(source)) | set(CREATE_TREEVIEW_RE.findall(source))


def oncommand_activation_targets(manifest):
    events = manifest.get("activationEvents", [])
    return {e.split(":", 1)[1] for e in events if e.startswith("onCommand:")}


def onview_activation_targets(manifest):
    events = manifest.get("activationEvents", [])
    return {e.split(":", 1)[1] for e in events if e.startswith("onView:")}


def menu_command_refs(manifest):
    refs = set()
    for entries in manifest.get("contributes", {}).get("menus", {}).values():
        for entry in entries:
            cmd = entry.get("command")
            if cmd:
                refs.add(cmd)
    return refs


def viewswelcome_command_refs(manifest):
    refs = set()
    for vw in manifest.get("contributes", {}).get("viewsWelcome", []):
        refs.update(COMMAND_URI_RE.findall(vw.get("contents", "")))
    return refs


def configured_property_short_keys(manifest):
    props = manifest.get("contributes", {}).get("configuration", {}).get("properties", {})
    return {k.split(".", 1)[1] if k.startswith("daedalus.") else k for k in props}


def configured_property_reads(source):
    return set(CFG_GET_RE.findall(source))


def parse_engine_version(spec):
    """Parse a `^X.Y.Z` / `~X.Y.Z` / `X.Y.Z` engines.vscode range into (major, minor, patch).

    Hand-written rather than regex: the grammar is small enough that plain
    string ops + int() are both a real parse (raises ValueError on garbage)
    and clearer than a pattern.
    """
    body = spec[1:] if spec[:1] in "^~" else spec
    parts = body.split(".")
    if len(parts) != 3:
        raise ValueError(f"expected X.Y.Z, got {spec!r}")
    return tuple(int(p) for p in parts)  # raises ValueError on non-numeric parts


MANIFEST = load_manifest()
SOURCE = load_source()


class ManifestJsonTests(unittest.TestCase):
    def test_package_json_parses_and_has_required_fields(self):
        for key in ("name", "version", "publisher", "engines", "main", "contributes"):
            self.assertIn(key, MANIFEST, f"package.json is missing required field {key!r}")


class CommandRegistrationConsistencyTests(unittest.TestCase):
    """Every contributed command must have a handler, and vice versa."""

    def test_every_declared_command_is_registered_in_source(self):
        declared = declared_commands(MANIFEST)
        registered = registered_commands(SOURCE)
        missing = declared - registered
        self.assertEqual(
            missing, set(),
            f"contributes.commands declares {sorted(missing)} but extension.js "
            "never calls vscode.commands.registerCommand() for them -- clicking "
            "these in VS Code would fail.",
        )

    def test_every_registered_command_is_declared(self):
        declared = declared_commands(MANIFEST)
        registered = registered_commands(SOURCE)
        extra = registered - declared
        self.assertEqual(
            extra, set(),
            f"extension.js registers {sorted(extra)} but contributes.commands "
            "never declares them -- dead code or an undocumented hidden command.",
        )


class ViewProviderConsistencyTests(unittest.TestCase):
    """Every contributed view needs a matching provider registration (and vice versa),
    the same shape of bug as commands but for the Activity Bar views: a declared
    webview/tree view with no provider renders as a permanently blank panel."""

    def test_every_webview_view_has_a_registered_provider(self):
        views = declared_views(MANIFEST)
        webview_ids = {vid for vid, vtype in views.items() if vtype == "webview"}
        registered = registered_webview_ids(SOURCE)
        missing = webview_ids - registered
        self.assertEqual(missing, set(), f"webview view(s) {sorted(missing)} have no registerWebviewViewProvider() call")

    def test_every_treeview_has_a_registered_provider(self):
        views = declared_views(MANIFEST)
        treeview_ids = {vid for vid, vtype in views.items() if vtype != "webview"}
        registered = registered_treeview_ids(SOURCE)
        missing = treeview_ids - registered
        self.assertEqual(missing, set(), f"tree view(s) {sorted(missing)} have no registerTreeDataProvider() call")

    def test_every_registered_provider_is_a_declared_view(self):
        declared_ids = set(declared_views(MANIFEST))
        registered = registered_webview_ids(SOURCE) | registered_treeview_ids(SOURCE)
        extra = registered - declared_ids
        self.assertEqual(extra, set(), f"extension.js registers provider(s) for undeclared view id(s) {sorted(extra)}")


class ActivationEventConsistencyTests(unittest.TestCase):
    def test_oncommand_events_reference_declared_commands(self):
        declared = declared_commands(MANIFEST)
        targets = oncommand_activation_targets(MANIFEST)
        stray = targets - declared
        self.assertEqual(stray, set(), f"activationEvents has onCommand: entries for undeclared command(s) {sorted(stray)}")

    def test_declared_commands_have_activation_events(self):
        # Not a hard VS Code requirement (since 1.74, contributed commands
        # activate implicitly) but this manifest's own convention is to list
        # every command explicitly, so a gap here is a real omission.
        declared = declared_commands(MANIFEST)
        targets = oncommand_activation_targets(MANIFEST)
        missing = declared - targets
        self.assertEqual(missing, set(), f"command(s) {sorted(missing)} declared but missing an onCommand: activation event")

    def test_onview_events_reference_declared_views(self):
        declared_ids = set(declared_views(MANIFEST))
        targets = onview_activation_targets(MANIFEST)
        stray = targets - declared_ids
        self.assertEqual(stray, set(), f"activationEvents has onView: entries for undeclared view id(s) {sorted(stray)}")

    def test_declared_views_have_activation_events(self):
        declared_ids = set(declared_views(MANIFEST))
        targets = onview_activation_targets(MANIFEST)
        missing = declared_ids - targets
        self.assertEqual(missing, set(), f"view id(s) {sorted(missing)} declared but missing an onView: activation event")


class MenuAndWelcomeReferenceTests(unittest.TestCase):
    """menus/* and viewsWelcome markdown links are a second, easy-to-miss place
    a command id can go stale after a rename."""

    def test_menu_entries_reference_declared_commands(self):
        declared = declared_commands(MANIFEST)
        refs = menu_command_refs(MANIFEST)
        stray = refs - declared
        self.assertEqual(stray, set(), f"contributes.menus references undeclared command(s) {sorted(stray)}")

    def test_viewswelcome_links_reference_declared_commands(self):
        declared = declared_commands(MANIFEST)
        refs = viewswelcome_command_refs(MANIFEST)
        stray = refs - declared
        self.assertEqual(stray, set(), f"viewsWelcome markdown links to undeclared command(s) {sorted(stray)}")


class ConfigurationPropertyUsageTests(unittest.TestCase):
    def test_configuration_properties_are_read_in_source(self):
        declared_keys = configured_property_short_keys(MANIFEST)
        used_keys = configured_property_reads(SOURCE)
        dead = declared_keys - used_keys
        self.assertEqual(dead, set(), f"configuration propert(y/ies) {sorted(dead)} declared but never read via cfg().get() in extension.js")


class MainEntryPointTests(unittest.TestCase):
    def test_main_field_points_to_an_existing_file(self):
        main_rel = MANIFEST["main"]
        main_path = (EXTENSION_DIR / main_rel).resolve()
        self.assertTrue(main_path.is_file(), f"package.json main={main_rel!r} does not exist on disk ({main_path})")

    def test_files_array_entries_exist(self):
        for rel in MANIFEST.get("files", []):
            self.assertTrue((EXTENSION_DIR / rel).exists(), f"'files' entry {rel!r} listed in package.json does not exist on disk")


class EditorContextAdapterTests(unittest.TestCase):
    """The VS Code adapter may capture explicit editor context, but must not
    turn it into a provider, queue, policy, or filesystem authority."""

    def test_ask_ikarus_uses_the_fixed_loopback_context_contract(self):
        self.assertIn('apiPost("/api/editor/contexts", {', SOURCE)
        self.assertIn("source: editorAdapterKind()", SOURCE)
        self.assertIn("path: relativePath", SOURCE)
        self.assertIn("start_line: range.start.line + 1", SOURCE)
        self.assertIn("start_column: range.start.character + 1", SOURCE)
        self.assertIn("end_line: range.end.line + 1", SOURCE)
        self.assertIn("end_column: range.end.character + 1", SOURCE)
        self.assertIn("response.body && response.body.context", SOURCE)
        self.assertIn("createdContext.context_ref", SOURCE)
        self.assertNotIn("relative_path:", SOURCE)
        self.assertNotIn("selection_truncated:", SOURCE)
        self.assertIn("const WEB_HOST = \"127.0.0.1\"", SOURCE)

    def test_oversize_editor_selection_is_visibly_refused_not_truncated(self):
        self.assertIn("if (selection.length > MAX_EDITOR_SELECTION_CHARS)", SOURCE)
        self.assertIn("above the ${MAX_EDITOR_SELECTION_CHARS}-character limit", SOURCE)
        self.assertNotIn("rawSelection.slice(0, MAX_EDITOR_SELECTION_CHARS)", SOURCE)

    def test_editor_context_never_uses_the_clipboard_or_project_json_writer(self):
        self.assertNotIn("vscode.env.clipboard.writeText", SOURCE)
        self.assertNotIn("fs.writeFileSync(project.path", SOURCE)

    def test_vsix_build_and_pinned_image_wire_the_same_local_adapter(self):
        scripts = MANIFEST.get("scripts", {})
        self.assertIn("build:vsix", scripts)
        self.assertIn("daedalus-vscode.vsix", scripts["build:vsix"])
        dockerfile = OPENVSCODE_DOCKERFILE.read_text(encoding="utf-8")
        self.assertIn("vscode-agent-env/dist/daedalus-vscode.vsix", dockerfile)
        self.assertIn("--install-extension /tmp/daedalus-vscode.vsix", dockerfile)


class EditorSessionAdapterTests(unittest.TestCase):
    """The transient editor session is restricted to exact UI navigation."""

    def test_session_contract_is_fixed_loopback_and_capability_allowlisted(self):
        self.assertIn('apiPost("/api/editor/sessions", body, 3000)', SOURCE)
        self.assertIn("body.base_revision = revision", SOURCE)
        self.assertIn('capabilities: ["reveal_location", "open_diff"]', SOURCE)
        self.assertIn('path: `/api/editor/sessions/${encodeURIComponent(session.id)}/events?${query.toString()}`', SOURCE)
        self.assertIn('wait_s: "25"', SOURCE)
        self.assertIn('"X-Daedalus-Editor-Token": session.token', SOURCE)
        self.assertIn("response.body && response.body.session", SOURCE)
        self.assertIn("created.session_token", SOURCE)
        self.assertIn('const editorSessions = new Map()', SOURCE)

    def test_session_event_handler_can_only_reveal_or_open_a_diff(self):
        start = SOURCE.index("async function applyEditorNavigation")
        end = SOURCE.index("function scheduleEditorSessionReconnect")
        handler = SOURCE[start:end]
        self.assertIn('event.command === "reveal_location"', handler)
        self.assertIn('event.command === "open_diff"', handler)
        self.assertIn("payload.path", handler)
        self.assertIn("payload.range", handler)
        self.assertIn('vscode.window.showTextDocument', handler)
        self.assertIn('"vscode.diff"', handler)
        self.assertNotIn("terminal(", handler)
        self.assertNotIn("enqueue(", handler)
        self.assertNotIn("writeFile", handler)

    def test_session_events_fail_closed_on_project_revision_and_path(self):
        self.assertIn("created.project !== project.name", SOURCE)
        self.assertIn("baseRevision !== revision", SOURCE)
        self.assertIn("function editorSessionRevisionMatches", SOURCE)
        self.assertIn("revision === session.baseRevision", SOURCE)
        self.assertIn('typeof event.created_at !== "string"', SOURCE)
        self.assertIn("function exactProjectFile", SOURCE)
        self.assertIn("fs.realpathSync", SOURCE)
        self.assertIn("relativePathWithin(root, candidate) === relativePath", SOURCE)

    def test_reconnect_reuses_only_memory_token_for_observation(self):
        start = SOURCE.index("function scheduleEditorSessionReconnect")
        end = SOURCE.index("async function ensureEditorSession")
        observer = SOURCE[start:end]
        self.assertIn("observeEditorSession(session)", observer)
        self.assertIn("session.after = event.sequence", observer)
        self.assertNotIn("apiPost(", observer)
        self.assertNotIn("globalState", SOURCE)
        self.assertNotIn("workspaceState", SOURCE)
        self.assertNotIn("secrets.store", SOURCE)


class EngineVersionTests(unittest.TestCase):
    def test_engines_vscode_present_and_parseable(self):
        engines = MANIFEST.get("engines", {})
        self.assertIn("vscode", engines, "package.json is missing engines.vscode")
        spec = engines["vscode"]
        try:
            major, minor, patch = parse_engine_version(spec)
        except ValueError as exc:
            self.fail(f"engines.vscode={spec!r} is not a parseable X.Y.Z version: {exc}")
        self.assertGreaterEqual(major, 1, f"engines.vscode={spec!r} has an implausible major version")


if __name__ == "__main__":
    unittest.main()

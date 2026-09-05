"""Deterministic, effect-free source rendering for bounded Genesis candidates.

``render_project`` only returns a finite mapping of safe POSIX-relative paths
to bytes.  It does not create a workspace, run a toolchain, persist artifacts,
or claim that the rendered source passed evaluation.  Those effects remain the
responsibility of the canonical Mission/Attempt/Evidence path.

The generated projects deliberately use only platform runtimes: a browser plus
the Python standard library for Web/PWA targets, and the Python standard
library for CLI targets.  No generated source contains an external endpoint,
credential, analytics hook, authentication flow, or dependency manifest.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import textwrap
import unicodedata
from pathlib import PurePosixPath
from typing import Mapping, Sequence


_TARGETS = frozenset({"web", "cli", "desktop", "mobile"})
ITEM_COLLECTION_BLUEPRINT = "item-collection-v1"
KANBAN_BOARD_BLUEPRINT = "kanban-board-v1"
_BLUEPRINTS = frozenset({ITEM_COLLECTION_BLUEPRINT, KANBAN_BOARD_BLUEPRINT})
_PRODUCT_LIMIT = 160
_PROMPT_LIMIT = 8_000
_SEARCH_FEATURE = "search and filter items"
_KANBAN_SEARCH_FEATURE = "search and filter cards"
_SUPPORTED_FEATURES = frozenset(
    {
        "complete and reopen items",
        "create local items",
        "delete local items",
        "edit local items",
        "persist data locally",
        _SEARCH_FEATURE,
    }
)
_KANBAN_SUPPORTED_FEATURES = frozenset(
    {
        "create local cards",
        "delete local cards",
        "edit local cards",
        "move cards between fixed columns",
        "persist data locally",
        _KANBAN_SEARCH_FEATURE,
    }
)


def _normalise_text(value: object, label: str, *, limit: int, multiline: bool) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    value = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    value = value.strip()
    if not value:
        raise ValueError(f"{label} must not be empty")
    if len(value) > limit:
        raise ValueError(f"{label} must be at most {limit} characters")
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL")
    if not multiline and any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} must be a single printable line")
    if multiline and any(
        ord(character) < 32 and character not in {"\n", "\t"}
        for character in value
    ):
        raise ValueError(f"{label} contains an unsupported control character")
    return value


def _normalise_target(target: object) -> str:
    if not isinstance(target, str):
        raise TypeError("target must be a string")
    value = target.strip().lower()
    if value not in _TARGETS:
        supported = ", ".join(sorted(_TARGETS))
        raise ValueError(f"target must be one of: {supported}")
    return value


def _normalise_blueprint(blueprint: object) -> str:
    if not isinstance(blueprint, str):
        raise TypeError("blueprint must be a string")
    value = blueprint.strip().lower()
    if value not in _BLUEPRINTS:
        supported = ", ".join(sorted(_BLUEPRINTS))
        raise ValueError(f"blueprint must be one of: {supported}")
    return value


def _slug(product_name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", product_name).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return (value or "project")[:64].rstrip("-")


def _normalise_features(features: Sequence[str]) -> tuple[str, ...]:
    if isinstance(features, (str, bytes)) or not isinstance(features, Sequence):
        raise TypeError("features must be a sequence of strings")
    normalised = tuple(
        sorted(
            {
                _normalise_text(feature, "feature", limit=200, multiline=False)
                for feature in features
            }
        )
    )
    unsupported = tuple(feature for feature in normalised if feature not in _SUPPORTED_FEATURES)
    if unsupported:
        raise ValueError("unsupported materialization features: " + ", ".join(unsupported))
    return normalised


def _normalise_kanban_features(features: Sequence[str]) -> tuple[str, ...]:
    if isinstance(features, (str, bytes)) or not isinstance(features, Sequence):
        raise TypeError("features must be a sequence of strings")
    normalised = tuple(
        sorted(
            {
                _normalise_text(feature, "feature", limit=200, multiline=False)
                for feature in features
            }
        )
    )
    unsupported = tuple(
        feature for feature in normalised if feature not in _KANBAN_SUPPORTED_FEATURES
    )
    if unsupported:
        raise ValueError(
            "unsupported kanban materialization features: " + ", ".join(unsupported)
        )
    return normalised


def _identity(
    prompt: str,
    product_name: str,
    target: str,
    features: tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "features": list(features),
            "product_name": product_name,
            "prompt": prompt,
            "target": target,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _kanban_identity(
    prompt: str,
    product_name: str,
    target: str,
    features: tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "blueprint": KANBAN_BOARD_BLUEPRINT,
            "features": list(features),
            "product_name": product_name,
            "prompt": prompt,
            "schema": "daedalus-genesis-materializer-identity/2",
            "target": target,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source(text: str) -> bytes:
    normalised = textwrap.dedent(text).lstrip("\n").rstrip() + "\n"
    return normalised.encode("utf-8")


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _safe_project(files: Mapping[str, bytes]) -> dict[str, bytes]:
    """Return a deterministically ordered, traversal-free source tree."""

    checked: dict[str, bytes] = {}
    folded: set[str] = set()
    for raw_path, payload in files.items():
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("generated paths must be non-empty strings")
        if "\\" in raw_path or "\x00" in raw_path or ":" in raw_path:
            raise ValueError(f"generated path is not a safe POSIX path: {raw_path!r}")
        path = PurePosixPath(raw_path)
        if path.is_absolute() or raw_path != path.as_posix():
            raise ValueError(f"generated path is not canonical: {raw_path!r}")
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"generated path escapes the candidate: {raw_path!r}")
        key = raw_path.casefold()
        if key in folded:
            raise ValueError(f"generated paths collide case-insensitively: {raw_path!r}")
        if not isinstance(payload, bytes):
            raise TypeError(f"generated payload must be bytes: {raw_path!r}")
        folded.add(key)
        checked[raw_path] = payload
    return {path: checked[path] for path in sorted(checked)}


def _quoted_markdown(value: str) -> str:
    return "\n".join("> " + line if line else ">" for line in value.split("\n"))


def _item_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {
            "details": {"type": "string"},
            "done": {"type": "boolean"},
            "id": {"minimum": 1, "type": "integer"},
            "title": {"minLength": 1, "type": "string"},
        },
        "required": ["id", "title", "details", "done"],
        "title": "Local item",
        "type": "object",
    }


def _card_schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "additionalProperties": False,
        "properties": {
            "column": {
                "enum": ["backlog", "in-progress", "done"],
                "type": "string",
            },
            "details": {"type": "string"},
            "id": {"minimum": 1, "type": "integer"},
            "title": {"minLength": 1, "type": "string"},
        },
        "required": ["id", "title", "details", "column"],
        "title": "Local kanban card",
        "type": "object",
    }


def _claims(code_file: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = [
        {
            "code_file": code_file,
            "kind": "code_declares_type",
            "type_file": code_file,
            "type_name": "Item",
        }
    ]
    for field in ("id", "title", "details", "done"):
        claims.append(
            {
                "kind": "type_matches_schema_field",
                "schema_field": field,
                "schema_file": "schemas/item.schema.json",
                "type_field": field,
                "type_file": code_file,
                "type_name": "Item",
            }
        )
    claims.extend(
        [
            {
                "kind": "wiki_documents_node",
                "link_target": code_file,
                "target_node_id": f"code:file:{code_file}",
                "target_plane": "code",
                "wiki_file": "README.md",
            },
            {
                "kind": "wiki_documents_node",
                "link_target": code_file,
                "target_node_id": f"type:{code_file}#Item",
                "target_plane": "type",
                "wiki_file": "README.md",
            },
            {
                "kind": "wiki_documents_node",
                "link_target": "schemas/item.schema.json",
                "target_node_id": "data:schema:schemas/item.schema.json",
                "target_plane": "data",
                "wiki_file": "README.md",
            },
        ]
    )
    return claims


def _fourfold(*, repository_id: str, code_files: list[str]) -> bytes:
    return _json_bytes(
        {
            "claims": _claims(code_files[0]),
            "code_files": code_files,
            "data_files": ["schemas/item.schema.json"],
            "knowledge_files": ["README.md"],
            "repository_id": repository_id,
            "schema": "daedalus-fourfold-reference/1",
        }
    )


def _kanban_claims(code_file: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = [
        {
            "code_file": code_file,
            "kind": "code_declares_type",
            "type_file": code_file,
            "type_name": "Card",
        }
    ]
    for field in ("id", "title", "details", "column"):
        claims.append(
            {
                "kind": "type_matches_schema_field",
                "schema_field": field,
                "schema_file": "schemas/card.schema.json",
                "type_field": field,
                "type_file": code_file,
                "type_name": "Card",
            }
        )
    claims.extend(
        [
            {
                "kind": "wiki_documents_node",
                "link_target": code_file,
                "target_node_id": f"code:file:{code_file}",
                "target_plane": "code",
                "wiki_file": "README.md",
            },
            {
                "kind": "wiki_documents_node",
                "link_target": code_file,
                "target_node_id": f"type:{code_file}#Card",
                "target_plane": "type",
                "wiki_file": "README.md",
            },
            {
                "kind": "wiki_documents_node",
                "link_target": "schemas/card.schema.json",
                "target_node_id": "data:schema:schemas/card.schema.json",
                "target_plane": "data",
                "wiki_file": "README.md",
            },
        ]
    )
    return claims


def _kanban_fourfold(*, repository_id: str) -> bytes:
    return _json_bytes(
        {
            "claims": _kanban_claims("model.py"),
            "code_files": ["model.py", "server.py", "app.js"],
            "data_files": ["schemas/card.schema.json"],
            "knowledge_files": ["README.md"],
            "repository_id": repository_id,
            "schema": "daedalus-fourfold-reference/1",
        }
    )


_ITEM_MODEL = """
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    # The local browser record described by schemas/item.schema.json.
    id: int
    title: str
    details: str
    done: bool
"""


_LOOPBACK_SERVER = """
from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000

    def __post_init__(self) -> None:
        if self.host != "127.0.0.1":
            raise ValueError("the generated server is loopback-only")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError("port must be an integer")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")


DEFAULT_CONFIG = ServerConfig()


def serve(config: ServerConfig = DEFAULT_CONFIG) -> None:
    if not isinstance(config, ServerConfig):
        raise TypeError("config must be ServerConfig")
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    with ThreadingHTTPServer((config.host, config.port), handler) as server:
        print(f"Serving locally at http://{config.host}:{config.port}")
        server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the generated PWA on loopback")
    parser.add_argument("--port", type=int, default=DEFAULT_CONFIG.port)
    args = parser.parse_args()
    serve(ServerConfig(port=args.port))


if __name__ == "__main__":
    main()
"""


_INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#172554">
  <meta name="description" content="Offline, local-first task collection">
  <link rel="manifest" href="manifest.webmanifest">
  <link rel="stylesheet" href="styles.css">
  <title>@@TITLE@@</title>
</head>
<body>
  <a class="skip-link" href="#main">Skip to the application</a>
  <header class="hero">
    <p class="eyebrow">Local-first Genesis candidate</p>
    <h1>@@HEADING@@</h1>
    <p id="objective" class="objective"></p>
  </header>
  <main id="main" class="layout" tabindex="-1">
    <section class="panel editor" aria-labelledby="editor-title">
      <h2 id="editor-title">Add an item</h2>
      <form id="item-form">
        <input id="editing-id" type="hidden">
        <label for="title">Title</label>
        <input id="title" name="title" maxlength="120" required autocomplete="off">
        <label for="details">Details</label>
        <textarea id="details" name="details" maxlength="1000" rows="5"></textarea>
        <div class="actions">
          <button id="save-button" type="submit">Add item</button>
          <button id="cancel-button" type="button" class="secondary" hidden>Cancel edit</button>
        </div>
      </form>
      <p id="status" role="status" aria-live="polite" class="status"></p>
    </section>
    <section class="panel collection" aria-labelledby="collection-title">
      <div class="section-heading">
        <h2 id="collection-title">Your items</h2>
        <span id="count" aria-live="polite"></span>
      </div>
      @@SEARCH_CONTROL@@
      <p id="empty-state">Nothing here yet. Add the first item.</p>
      <ul id="items" class="items" aria-label="Saved items"></ul>
    </section>
  </main>
  <footer>Stored only in this browser. No account, analytics, or remote service.</footer>
  <script src="app.js" defer></script>
</body>
</html>
"""


_STYLES = """
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f8fafc;
  color: #172033;
  --accent: #1d4ed8;
  --accent-dark: #172554;
  --border: #cbd5e1;
  --surface: #ffffff;
}

* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; }
button, input, textarea { font: inherit; }
button, input, textarea { min-height: 44px; }
.skip-link { position: absolute; left: -10000px; top: 0; }
.skip-link:focus { left: 1rem; top: 1rem; z-index: 10; background: white; padding: .75rem; }
.hero { padding: clamp(2rem, 7vw, 5rem) max(1rem, calc((100vw - 72rem) / 2)); background: var(--accent-dark); color: white; }
.hero h1 { margin: .25rem 0 .75rem; font-size: clamp(2rem, 6vw, 4rem); line-height: 1; }
.eyebrow { margin: 0; text-transform: uppercase; letter-spacing: .12em; font-weight: 700; }
.objective { max-width: 60ch; line-height: 1.6; }
.layout { width: min(72rem, calc(100% - 2rem)); margin: -1.5rem auto 2rem; display: grid; grid-template-columns: minmax(16rem, 2fr) minmax(20rem, 3fr); gap: 1rem; align-items: start; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 1rem; padding: clamp(1rem, 3vw, 1.5rem); box-shadow: 0 12px 35px rgb(15 23 42 / .08); }
form { display: grid; gap: .65rem; }
label { font-weight: 700; }
input, textarea { width: 100%; border: 1px solid #94a3b8; border-radius: .55rem; padding: .7rem; color: inherit; background: white; }
input:focus, textarea:focus, button:focus-visible { outline: 3px solid #93c5fd; outline-offset: 2px; }
.actions, .section-heading, .item-actions { display: flex; gap: .6rem; align-items: center; flex-wrap: wrap; }
.section-heading { justify-content: space-between; }
.collection-search { display: grid; gap: .4rem; margin: .25rem 0 1rem; }
button { border: 0; border-radius: .55rem; padding: .65rem 1rem; background: var(--accent); color: white; font-weight: 700; cursor: pointer; }
button.secondary { color: var(--accent-dark); background: #dbeafe; }
button.danger { color: #7f1d1d; background: #fee2e2; }
.items { list-style: none; margin: 0; padding: 0; display: grid; gap: .75rem; }
.item { border: 1px solid var(--border); border-radius: .75rem; padding: 1rem; display: grid; gap: .65rem; }
.item.done h3 { text-decoration: line-through; color: #64748b; }
.item-title { display: flex; align-items: flex-start; gap: .75rem; }
.item-title input { width: 1.25rem; min-height: 1.25rem; margin-top: .2rem; }
.item h3, .item p { margin: 0; }
.item p { white-space: pre-wrap; line-height: 1.5; }
.status { min-height: 1.5rem; }
footer { text-align: center; color: #475569; padding: 1rem 1rem 2rem; }

@media (max-width: 760px) {
  .layout { grid-template-columns: 1fr; margin-top: 1rem; }
  .hero { padding-bottom: 2rem; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; }
}
"""


_WEB_APP = r"""
'use strict';

const CONFIG = Object.freeze(@@CONFIG@@);
const form = document.querySelector('#item-form');
const titleInput = document.querySelector('#title');
const detailsInput = document.querySelector('#details');
const editingInput = document.querySelector('#editing-id');
const saveButton = document.querySelector('#save-button');
const cancelButton = document.querySelector('#cancel-button');
const list = document.querySelector('#items');
const emptyState = document.querySelector('#empty-state');
const count = document.querySelector('#count');
const status = document.querySelector('#status');
const filterInput = document.querySelector('#filter');
document.querySelector('#objective').textContent = CONFIG.objective;

function blankState() {
  return { version: 1, nextId: 1, items: [] };
}

let storageAvailable = true;

function readState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CONFIG.storageKey) || 'null');
    if (!parsed || parsed.version !== 1 || !Number.isInteger(parsed.nextId) || !Array.isArray(parsed.items)) return blankState();
    return parsed;
  } catch (_) {
    storageAvailable = false;
    return blankState();
  }
}

let state = readState();

function persist() {
  try {
    localStorage.setItem(CONFIG.storageKey, JSON.stringify(state));
  } catch (_) {
    storageAvailable = false;
  }
}

function announce(message) {
  const storageNote = storageAvailable ? '' : ' Preview sandbox keeps changes until reload.';
  status.textContent = '';
  window.requestAnimationFrame(() => { status.textContent = message + storageNote; });
}

function button(label, className, action) {
  const node = document.createElement('button');
  node.type = 'button';
  node.textContent = label;
  if (className) node.className = className;
  node.addEventListener('click', action);
  return node;
}

function filterItems(items, query) {
  const needle = String(query || '').trim().toLocaleLowerCase();
  if (!needle) return items;
  return items.filter((item) =>
    item.title.toLocaleLowerCase().includes(needle)
    || item.details.toLocaleLowerCase().includes(needle)
  );
}

function render() {
  list.replaceChildren();
  const visibleItems = filterItems(state.items, filterInput ? filterInput.value : '');
  for (const item of visibleItems) {
    const row = document.createElement('li');
    row.className = 'item' + (item.done ? ' done' : '');

    const heading = document.createElement('div');
    heading.className = 'item-title';
    const toggle = document.createElement('input');
    toggle.type = 'checkbox';
    toggle.checked = Boolean(item.done);
    toggle.setAttribute('aria-label', 'Mark ' + item.title + ' complete');
    toggle.addEventListener('change', () => toggleItem(item.id));
    const title = document.createElement('h3');
    title.textContent = item.title;
    heading.append(toggle, title);

    const details = document.createElement('p');
    details.textContent = item.details || 'No details';
    const actions = document.createElement('div');
    actions.className = 'item-actions';
    actions.append(
      button('Edit', 'secondary', () => beginEdit(item.id)),
      button('Delete', 'danger', () => deleteItem(item.id))
    );
    row.append(heading, details, actions);
    list.append(row);
  }
  emptyState.hidden = visibleItems.length !== 0;
  emptyState.textContent = state.items.length === 0
    ? 'Nothing here yet. Add the first item.'
    : 'No items match this filter.';
  count.textContent = filterInput && filterInput.value.trim()
    ? visibleItems.length + ' of ' + state.items.length + ' items'
    : state.items.length + (state.items.length === 1 ? ' item' : ' items');
}

function createItem(title, details) {
  state.items.push({ id: state.nextId, title, details, done: false });
  state.nextId += 1;
  persist();
  announce('Item added.');
}

function updateItem(id, title, details) {
  const item = state.items.find((candidate) => candidate.id === id);
  if (!item) return;
  item.title = title;
  item.details = details;
  persist();
  announce('Item updated.');
}

function deleteItem(id) {
  state.items = state.items.filter((item) => item.id !== id);
  if (Number(editingInput.value) === id) resetEditor();
  persist();
  render();
  announce('Item deleted.');
}

function toggleItem(id) {
  const item = state.items.find((candidate) => candidate.id === id);
  if (!item) return;
  item.done = !item.done;
  persist();
  render();
  announce(item.done ? 'Item completed.' : 'Item reopened.');
}

function beginEdit(id) {
  const item = state.items.find((candidate) => candidate.id === id);
  if (!item) return;
  editingInput.value = String(id);
  titleInput.value = item.title;
  detailsInput.value = item.details;
  document.querySelector('#editor-title').textContent = 'Edit item';
  saveButton.textContent = 'Save changes';
  cancelButton.hidden = false;
  titleInput.focus();
}

function resetEditor() {
  form.reset();
  editingInput.value = '';
  document.querySelector('#editor-title').textContent = 'Add an item';
  saveButton.textContent = 'Add item';
  cancelButton.hidden = true;
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const title = titleInput.value.trim();
  const details = detailsInput.value.trim();
  if (!title) {
    announce('Enter a title.');
    titleInput.focus();
    return;
  }
  const editing = Number(editingInput.value);
  if (Number.isInteger(editing) && editing > 0) updateItem(editing, title, details);
  else createItem(title, details);
  resetEditor();
  render();
});

cancelButton.addEventListener('click', () => {
  resetEditor();
  announce('Edit cancelled.');
});

if (filterInput) filterInput.addEventListener('input', render);

render();
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    try {
      navigator.serviceWorker.register('./service-worker.js').catch(() => {});
    } catch (_) {}
  });
}
"""


_SERVICE_WORKER = """
'use strict';

const CACHE_NAME = '@@CACHE@@';
const APP_SHELL = [
  './',
  './index.html',
  './styles.css',
  './app.js',
  './manifest.webmanifest',
  './icons/icon-192.svg',
  './icons/icon-512.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) => Promise.all(
      names.filter((name) => name !== CACHE_NAME).map((name) => caches.delete(name))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
      .catch(() => caches.match('./index.html'))
  );
});
"""


_WEB_TEST = """
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server


class GeneratedWebProjectTest(unittest.TestCase):
    def test_pwa_shell_is_local_and_complete(self) -> None:
        manifest = json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "./")
        for path in ("index.html", "styles.css", "app.js", "service-worker.js"):
            self.assertTrue((ROOT / path).is_file(), path)

    def test_crud_uses_browser_local_storage(self) -> None:
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        for name in ("createItem", "updateItem", "deleteItem", "toggleItem"):
            self.assertIn("function " + name, source)
        self.assertIn("localStorage", source)
        self.assertNotIn("https://", source)

    def test_server_cannot_bind_beyond_loopback(self) -> None:
        self.assertEqual(server.DEFAULT_CONFIG.host, "127.0.0.1")
        with self.assertRaises(ValueError):
            server.ServerConfig(host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
"""


_CLI_APP = r'''
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any


PRODUCT_NAME = @@PRODUCT@@
OBJECTIVE = @@PROMPT@@
SEARCH_ENABLED = @@SEARCH_ENABLED@@
DEFAULT_DATA = Path(__file__).with_name("items.json")


@dataclass(frozen=True)
class Item:
    id: int
    title: str
    details: str
    done: bool


def _blank() -> dict[str, Any]:
    return {"items": [], "next_id": 1, "version": 1}


def load(path: Path = DEFAULT_DATA) -> dict[str, Any]:
    if not path.exists():
        return _blank()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("local data is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("local data has an unsupported shape")
    if not isinstance(value.get("items"), list) or not isinstance(value.get("next_id"), int):
        raise ValueError("local data has an unsupported shape")
    return value


def save(state: dict[str, Any], path: Path = DEFAULT_DATA) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".items-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def items(path: Path = DEFAULT_DATA) -> list[Item]:
    return [Item(**row) for row in load(path)["items"]]


def search(query: str, path: Path = DEFAULT_DATA) -> list[Item]:
    needle = query.strip().casefold()
    if not needle:
        raise ValueError("query must not be empty")
    return [
        item
        for item in items(path)
        if needle in item.title.casefold() or needle in item.details.casefold()
    ]


def add(title: str, details: str = "", path: Path = DEFAULT_DATA) -> Item:
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    state = load(path)
    item = Item(id=state["next_id"], title=title, details=details.strip(), done=False)
    state["next_id"] += 1
    state["items"].append(asdict(item))
    save(state, path)
    return item


def update(item_id: int, title: str, details: str, path: Path = DEFAULT_DATA) -> Item:
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    state = load(path)
    for index, row in enumerate(state["items"]):
        if row.get("id") == item_id:
            item = Item(id=item_id, title=title, details=details.strip(), done=bool(row.get("done")))
            state["items"][index] = asdict(item)
            save(state, path)
            return item
    raise KeyError(f"item {item_id} does not exist")


def toggle(item_id: int, path: Path = DEFAULT_DATA) -> Item:
    state = load(path)
    for index, row in enumerate(state["items"]):
        if row.get("id") == item_id:
            item = Item(id=item_id, title=str(row["title"]), details=str(row.get("details", "")), done=not bool(row.get("done")))
            state["items"][index] = asdict(item)
            save(state, path)
            return item
    raise KeyError(f"item {item_id} does not exist")


def delete(item_id: int, path: Path = DEFAULT_DATA) -> None:
    state = load(path)
    retained = [row for row in state["items"] if row.get("id") != item_id]
    if len(retained) == len(state["items"]):
        raise KeyError(f"item {item_id} does not exist")
    state["items"] = retained
    save(state, path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=PRODUCT_NAME + " — local JSON CRUD")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="local JSON file")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    if SEARCH_ENABLED:
        search_parser = commands.add_parser("search")
        search_parser.add_argument("query")
    add_parser = commands.add_parser("add")
    add_parser.add_argument("title")
    add_parser.add_argument("--details", default="")
    update_parser = commands.add_parser("update")
    update_parser.add_argument("id", type=int)
    update_parser.add_argument("title")
    update_parser.add_argument("--details", default="")
    for name in ("toggle", "delete"):
        child = commands.add_parser(name)
        child.add_argument("id", type=int)
    commands.add_parser("about")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "list":
        result: object = [asdict(item) for item in items(args.data)]
    elif args.command == "search":
        result = [asdict(item) for item in search(args.query, args.data)]
    elif args.command == "add":
        result = asdict(add(args.title, args.details, args.data))
    elif args.command == "update":
        result = asdict(update(args.id, args.title, args.details, args.data))
    elif args.command == "toggle":
        result = asdict(toggle(args.id, args.data))
    elif args.command == "delete":
        delete(args.id, args.data)
        result = {"deleted": args.id}
    else:
        result = {"objective": OBJECTIVE, "product_name": PRODUCT_NAME}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
'''


_CLI_TEST = """
from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app


class GeneratedCliProjectTest(unittest.TestCase):
    def test_crud_round_trip_is_local_and_canonical(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.json"
            first = app.add("First", "Local", path)
            second = app.add("Second", "Only", path)
            self.assertEqual([item.id for item in app.items(path)], [1, 2])
            changed = app.update(first.id, "Renamed", "Still local", path)
            self.assertEqual(changed.title, "Renamed")
            self.assertTrue(app.toggle(second.id, path).done)
            app.delete(first.id, path)
            self.assertEqual([item.id for item in app.items(path)], [2])
            parsed = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["next_id"], 3)
            self.assertTrue(path.read_bytes().endswith(b"\\n"))
            if app.SEARCH_ENABLED:
                self.assertEqual([item.id for item in app.search("ONLY", path)], [2])

    def test_empty_titles_are_refused_without_a_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "items.json"
            with self.assertRaises(ValueError):
                app.add("   ", path=path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
"""


def _icon(size: int) -> bytes:
    return _source(
        f"""
        <svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 100 100" role="img" aria-label="Local collection">
          <rect width="100" height="100" rx="22" fill="#172554"/>
          <path d="M25 29h50v9H25zm0 20h50v9H25zm0 20h34v9H25z" fill="#bfdbfe"/>
        </svg>
        """
    )


def _web_readme(
    product_name: str,
    prompt: str,
    target: str,
    *,
    search_enabled: bool,
) -> bytes:
    target_note = {
        "web": "This is a local, installable browser PWA served from loopback.",
        "desktop": (
            "This is an installable PWA candidate, not a native desktop application. "
            "It has not been packaged, signed, or published to an app store."
        ),
        "mobile": (
            "This is an installable PWA candidate, not a native Android or iOS application. "
            "It has not been signed or published to a mobile app store."
        ),
    }[target]
    search_note = (
        "Use the labelled search field to filter item titles and details locally."
        if search_enabled
        else "This candidate did not request a search or filter control."
    )
    return _source(
        f"""
        # {product_name}

        {_quoted_markdown(prompt)}

        ## Target

        {target_note}

        ## Run locally

        ```console
        python server.py --port 8000
        ```

        Open `http://127.0.0.1:8000`. The server refuses non-loopback binds.

        ## Test

        ```console
        python -m unittest discover -s tests
        ```

        ## Data and privacy

        Items stay in browser `localStorage`. The application has no account,
        login, telemetry, paid service, external dependency, or external network
        endpoint. Its service worker caches only same-origin application files.
        {search_note}

        The Fourfold reference binds the [item model](model.py) and its
        [local schema](schemas/item.schema.json) to this documentation.
        """
    )


def _cli_readme(
    product_name: str,
    prompt: str,
    *,
    search_enabled: bool,
) -> bytes:
    search_example = (
        '\n        python app.py search "local"'
        if search_enabled
        else ""
    )
    return _source(
        f"""
        # {product_name}

        {_quoted_markdown(prompt)}

        ## Run

        ```console
        python app.py list
        python app.py add "First item" --details "Stored locally"
        python app.py update 1 "Renamed" --details "Still local"
        python app.py toggle 1
        python app.py delete 1
        {search_example}
        ```

        Use `--data PATH` before the subcommand to select another local JSON
        file. The app uses only Python's standard library and has no login,
        telemetry, paid service, secret, or network endpoint.

        ## Test

        ```console
        python -m unittest discover -s tests
        ```

        The Fourfold reference binds the [CLI item model](app.py) and its
        [local schema](schemas/item.schema.json) to this documentation.
        """
    )


def _render_web(
    prompt: str,
    product_name: str,
    target: str,
    digest: str,
    *,
    search_enabled: bool,
) -> dict[str, bytes]:
    manifest = {
        "background_color": "#f8fafc",
        "description": prompt,
        "display": "standalone",
        "icons": [
            {"sizes": "192x192", "src": "icons/icon-192.svg", "type": "image/svg+xml"},
            {"sizes": "512x512", "src": "icons/icon-512.svg", "type": "image/svg+xml"},
        ],
        "id": "./",
        "name": product_name,
        "scope": "./",
        "short_name": product_name[:30],
        "start_url": "./",
        "theme_color": "#172554",
    }
    config = json.dumps(
        {
            "objective": prompt,
            "productName": product_name,
            "storageKey": f"genesis-{digest[:20]}",
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    app_source = _WEB_APP.replace("@@CONFIG@@", config)
    service_worker = _SERVICE_WORKER.replace("@@CACHE@@", f"genesis-{digest[:20]}")
    repository_id = f"genesis/{_slug(product_name)}-{target}-{digest[:12]}"
    return {
        "README.md": _web_readme(
            product_name,
            prompt,
            target,
            search_enabled=search_enabled,
        ),
        "app.js": _source(app_source),
        "fourfold.json": _fourfold(
            repository_id=repository_id,
            # Keep model.py first because _claims binds Item's typed schema
            # evidence to that file; app.js is nevertheless authoritative code
            # and must be present in the rebuilt code plane.
            code_files=["model.py", "server.py", "app.js"],
        ),
        "icons/icon-192.svg": _icon(192),
        "icons/icon-512.svg": _icon(512),
        "index.html": _source(
            _INDEX_HTML.replace("@@TITLE@@", html.escape(product_name, quote=True))
            .replace("@@HEADING@@", html.escape(product_name, quote=True))
            .replace(
                "@@SEARCH_CONTROL@@",
                (
                    '<div class="collection-search">\n'
                    '  <label for="filter">Search items</label>\n'
                    '  <input id="filter" type="search" '
                    'placeholder="Filter titles and details" autocomplete="off">\n'
                    '</div>'
                    if search_enabled
                    else ""
                ),
            )
        ),
        "manifest.webmanifest": _json_bytes(manifest),
        "model.py": _source(_ITEM_MODEL),
        "schemas/item.schema.json": _json_bytes(_item_schema()),
        "server.py": _source(_LOOPBACK_SERVER),
        "service-worker.js": _source(service_worker),
        "styles.css": _source(_STYLES),
        "tests/test_project.py": _source(_WEB_TEST),
    }


def _render_cli(
    prompt: str,
    product_name: str,
    digest: str,
    *,
    search_enabled: bool,
) -> dict[str, bytes]:
    app_source = _CLI_APP.replace(
        "@@PRODUCT@@", json.dumps(product_name, ensure_ascii=True)
    ).replace("@@PROMPT@@", json.dumps(prompt, ensure_ascii=True)).replace(
        "@@SEARCH_ENABLED@@", "True" if search_enabled else "False"
    )
    repository_id = f"genesis/{_slug(product_name)}-cli-{digest[:12]}"
    return {
        "README.md": _cli_readme(
            product_name,
            prompt,
            search_enabled=search_enabled,
        ),
        "app.py": _source(app_source),
        "fourfold.json": _fourfold(repository_id=repository_id, code_files=["app.py"]),
        "schemas/item.schema.json": _json_bytes(_item_schema()),
        "tests/test_app.py": _source(_CLI_TEST),
    }


_KANBAN_MODEL = """
from __future__ import annotations

from dataclasses import dataclass


COLUMNS: tuple[str, ...] = ("backlog", "in-progress", "done")


@dataclass(frozen=True)
class Card:
    # The local browser record described by schemas/card.schema.json.
    id: int
    title: str
    details: str
    column: str

    def __post_init__(self) -> None:
        if self.column not in COLUMNS:
            raise ValueError("column must be backlog, in-progress, or done")
"""


_KANBAN_INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#312e81">
  <meta name="description" content="Offline, local-first kanban board">
  <link rel="manifest" href="manifest.webmanifest">
  <link rel="stylesheet" href="styles.css">
  <title>@@TITLE@@</title>
</head>
<body>
  <a class="skip-link" href="#main">Skip to the application</a>
  <header class="hero">
    <p class="eyebrow">Local-first Genesis kanban candidate</p>
    <h1>@@HEADING@@</h1>
    <p id="objective" class="objective"></p>
  </header>
  <main id="main" class="layout" tabindex="-1">
    <section class="panel editor" aria-labelledby="editor-title">
      <h2 id="editor-title">Add a card</h2>
      <form id="card-form">
        <input id="editing-id" type="hidden">
        <label for="title">Title</label>
        <input id="title" name="title" maxlength="120" required autocomplete="off">
        <label for="details">Details</label>
        <textarea id="details" name="details" maxlength="1000" rows="4"></textarea>
        <div class="actions">
          <button id="save-button" type="submit">Add card</button>
          <button id="cancel-button" type="button" class="secondary" hidden>Cancel edit</button>
        </div>
      </form>
      <p id="status" role="status" aria-live="polite" class="status"></p>
    </section>
    <section class="board-panel" aria-labelledby="board-title">
      <div class="section-heading">
        <h2 id="board-title">Board</h2>
        <span id="count" aria-live="polite"></span>
      </div>
      @@SEARCH_CONTROL@@
      <div class="kanban-board">
        <section class="kanban-column" data-column="backlog" aria-labelledby="backlog-title">
          <h3 id="backlog-title">Backlog</h3>
          <p id="backlog-empty" class="empty-state">No backlog cards.</p>
          <ul id="backlog-cards" class="cards" aria-label="Backlog cards"></ul>
        </section>
        <section class="kanban-column" data-column="in-progress" aria-labelledby="in-progress-title">
          <h3 id="in-progress-title">In Progress</h3>
          <p id="in-progress-empty" class="empty-state">No cards in progress.</p>
          <ul id="in-progress-cards" class="cards" aria-label="In progress cards"></ul>
        </section>
        <section class="kanban-column" data-column="done" aria-labelledby="done-title">
          <h3 id="done-title">Done</h3>
          <p id="done-empty" class="empty-state">No completed cards.</p>
          <ul id="done-cards" class="cards" aria-label="Done cards"></ul>
        </section>
      </div>
    </section>
  </main>
  <footer>Stored only in this browser. No account, analytics, or remote service.</footer>
  <script src="app.js" defer></script>
</body>
</html>
"""


_KANBAN_STYLES = """
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f8fafc;
  color: #172033;
  --accent: #4f46e5;
  --accent-dark: #312e81;
  --border: #cbd5e1;
  --surface: #ffffff;
}

* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; }
button, input, textarea { font: inherit; min-height: 44px; }
.skip-link { position: absolute; left: -10000px; top: 0; }
.skip-link:focus { left: 1rem; top: 1rem; z-index: 10; background: white; padding: .75rem; }
.hero { padding: clamp(2rem, 7vw, 5rem) max(1rem, calc((100vw - 88rem) / 2)); background: var(--accent-dark); color: white; }
.hero h1 { margin: .25rem 0 .75rem; font-size: clamp(2rem, 6vw, 4rem); line-height: 1; }
.eyebrow { margin: 0; text-transform: uppercase; letter-spacing: .12em; font-weight: 700; }
.objective { max-width: 60ch; line-height: 1.6; }
.layout { width: min(88rem, calc(100% - 2rem)); margin: -1.5rem auto 2rem; display: grid; grid-template-columns: minmax(16rem, 20rem) minmax(0, 1fr); gap: 1rem; align-items: start; }
.panel, .board-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 1rem; padding: clamp(1rem, 3vw, 1.5rem); box-shadow: 0 12px 35px rgb(15 23 42 / .08); }
form { display: grid; gap: .65rem; }
label { font-weight: 700; }
input, textarea { width: 100%; border: 1px solid #94a3b8; border-radius: .55rem; padding: .7rem; color: inherit; background: white; }
input:focus, textarea:focus, button:focus-visible { outline: 3px solid #a5b4fc; outline-offset: 2px; }
.actions, .section-heading, .card-actions { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; }
.section-heading { justify-content: space-between; }
.board-search { display: grid; gap: .4rem; margin: .25rem 0 1rem; }
button { border: 0; border-radius: .55rem; padding: .65rem .85rem; background: var(--accent); color: white; font-weight: 700; cursor: pointer; }
button.secondary { color: var(--accent-dark); background: #e0e7ff; }
button.danger { color: #7f1d1d; background: #fee2e2; }
.kanban-board { display: grid; grid-template-columns: repeat(3, minmax(12rem, 1fr)); gap: .75rem; align-items: start; overflow-x: auto; }
.kanban-column { min-width: 12rem; border: 1px solid var(--border); border-radius: .8rem; padding: .8rem; background: #f8fafc; }
.kanban-column h3 { margin: 0 0 .75rem; }
.cards { list-style: none; margin: 0; padding: 0; display: grid; gap: .65rem; }
.card { border: 1px solid var(--border); border-radius: .7rem; padding: .8rem; background: white; display: grid; gap: .55rem; }
.card h4, .card p { margin: 0; }
.card p { white-space: pre-wrap; line-height: 1.45; }
.card-actions button { flex: 1 1 auto; }
.empty-state { color: #64748b; }
.status { min-height: 1.5rem; }
footer { text-align: center; color: #475569; padding: 1rem 1rem 2rem; }

@media (max-width: 760px) {
  .layout { grid-template-columns: 1fr; margin-top: 1rem; }
  .hero { padding-bottom: 2rem; }
  .kanban-board { grid-template-columns: 1fr; overflow: visible; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; }
}
"""


_KANBAN_APP = r"""
'use strict';

const CONFIG = Object.freeze(@@CONFIG@@);
const COLUMNS = Object.freeze(['backlog', 'in-progress', 'done']);
const form = document.querySelector('#card-form');
const titleInput = document.querySelector('#title');
const detailsInput = document.querySelector('#details');
const editingInput = document.querySelector('#editing-id');
const saveButton = document.querySelector('#save-button');
const cancelButton = document.querySelector('#cancel-button');
const count = document.querySelector('#count');
const status = document.querySelector('#status');
const filterInput = document.querySelector('#filter');
const lists = Object.freeze({
  backlog: document.querySelector('#backlog-cards'),
  'in-progress': document.querySelector('#in-progress-cards'),
  done: document.querySelector('#done-cards')
});
const emptyStates = Object.freeze({
  backlog: document.querySelector('#backlog-empty'),
  'in-progress': document.querySelector('#in-progress-empty'),
  done: document.querySelector('#done-empty')
});
document.querySelector('#objective').textContent = CONFIG.objective;

function blankState() {
  return { version: 1, nextId: 1, cards: [] };
}

let storageAvailable = true;

function validCard(card) {
  return card
    && Number.isInteger(card.id)
    && typeof card.title === 'string'
    && typeof card.details === 'string'
    && COLUMNS.includes(card.column);
}

function readState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(CONFIG.storageKey) || 'null');
    if (!parsed || parsed.version !== 1 || !Number.isInteger(parsed.nextId) || !Array.isArray(parsed.cards)) return blankState();
    if (!parsed.cards.every(validCard)) return blankState();
    return parsed;
  } catch (_) {
    storageAvailable = false;
    return blankState();
  }
}

let state = readState();

function persist() {
  try {
    localStorage.setItem(CONFIG.storageKey, JSON.stringify(state));
  } catch (_) {
    storageAvailable = false;
  }
}

function announce(message) {
  const storageNote = storageAvailable ? '' : ' Preview sandbox keeps changes until reload.';
  status.textContent = '';
  window.requestAnimationFrame(() => { status.textContent = message + storageNote; });
}

function button(label, className, action) {
  const node = document.createElement('button');
  node.type = 'button';
  node.textContent = label;
  if (className) node.className = className;
  node.addEventListener('click', action);
  return node;
}

function filterCards(cards, query) {
  const needle = String(query || '').trim().toLocaleLowerCase();
  if (!needle) return cards;
  return cards.filter((card) =>
    card.title.toLocaleLowerCase().includes(needle)
    || card.details.toLocaleLowerCase().includes(needle)
  );
}

function render() {
  for (const column of COLUMNS) lists[column].replaceChildren();
  const visibleCards = filterCards(state.cards, filterInput ? filterInput.value : '');
  for (const card of visibleCards) {
    const row = document.createElement('li');
    row.className = 'card';
    const title = document.createElement('h4');
    title.textContent = card.title;
    const details = document.createElement('p');
    details.textContent = card.details || 'No details';
    const actions = document.createElement('div');
    actions.className = 'card-actions';
    const columnIndex = COLUMNS.indexOf(card.column);
    if (columnIndex > 0) {
      actions.append(button('Move Back', 'secondary', () => moveCard(card.id, -1)));
    }
    if (columnIndex < COLUMNS.length - 1) {
      actions.append(button('Move Forward', '', () => moveCard(card.id, 1)));
    }
    actions.append(
      button('Edit', 'secondary', () => beginEdit(card.id)),
      button('Delete', 'danger', () => deleteCard(card.id))
    );
    row.append(title, details, actions);
    lists[card.column].append(row);
  }
  for (const column of COLUMNS) {
    emptyStates[column].hidden = visibleCards.some((card) => card.column === column);
  }
  count.textContent = filterInput && filterInput.value.trim()
    ? visibleCards.length + ' of ' + state.cards.length + ' cards'
    : state.cards.length + (state.cards.length === 1 ? ' card' : ' cards');
}

function createCard(title, details) {
  state.cards.push({ id: state.nextId, title, details, column: 'backlog' });
  state.nextId += 1;
  persist();
  announce('Card added to Backlog.');
}

function updateCard(id, title, details) {
  const card = state.cards.find((candidate) => candidate.id === id);
  if (!card) return;
  card.title = title;
  card.details = details;
  persist();
  announce('Card updated.');
}

function deleteCard(id) {
  state.cards = state.cards.filter((card) => card.id !== id);
  if (Number(editingInput.value) === id) resetEditor();
  persist();
  render();
  announce('Card deleted.');
}

function moveCard(id, direction) {
  const card = state.cards.find((candidate) => candidate.id === id);
  if (!card || !Number.isInteger(direction) || Math.abs(direction) !== 1) return;
  const current = COLUMNS.indexOf(card.column);
  const next = current + direction;
  if (current < 0 || next < 0 || next >= COLUMNS.length) return;
  card.column = COLUMNS[next];
  persist();
  render();
  announce('Card moved to ' + card.column + '.');
}

function beginEdit(id) {
  const card = state.cards.find((candidate) => candidate.id === id);
  if (!card) return;
  editingInput.value = String(id);
  titleInput.value = card.title;
  detailsInput.value = card.details;
  document.querySelector('#editor-title').textContent = 'Edit card';
  saveButton.textContent = 'Save changes';
  cancelButton.hidden = false;
  titleInput.focus();
}

function resetEditor() {
  form.reset();
  editingInput.value = '';
  document.querySelector('#editor-title').textContent = 'Add a card';
  saveButton.textContent = 'Add card';
  cancelButton.hidden = true;
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const title = titleInput.value.trim();
  const details = detailsInput.value.trim();
  if (!title) {
    announce('Enter a title.');
    titleInput.focus();
    return;
  }
  const editing = Number(editingInput.value);
  if (Number.isInteger(editing) && editing > 0) updateCard(editing, title, details);
  else createCard(title, details);
  resetEditor();
  render();
});

cancelButton.addEventListener('click', () => {
  resetEditor();
  announce('Edit cancelled.');
});

if (filterInput) filterInput.addEventListener('input', render);

render();
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    try {
      navigator.serviceWorker.register('./service-worker.js').catch(() => {});
    } catch (_) {}
  });
}
"""


_KANBAN_TEST = """
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import model
import server


class GeneratedKanbanProjectTest(unittest.TestCase):
    def test_fixed_card_contract_and_pwa_shell(self) -> None:
        manifest = json.loads((ROOT / "manifest.webmanifest").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "schemas/card.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "./")
        self.assertEqual(model.COLUMNS, ("backlog", "in-progress", "done"))
        self.assertEqual(schema["properties"]["column"]["enum"], list(model.COLUMNS))
        self.assertEqual(model.Card(1, "First", "Local", "backlog").column, "backlog")
        with self.assertRaises(ValueError):
            model.Card(2, "Bad", "Column", "custom")

    def test_keyboard_crud_and_movement_are_local(self) -> None:
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        for name in ("createCard", "updateCard", "deleteCard", "moveCard"):
            self.assertIn("function " + name, source)
        self.assertIn("Move Back", source)
        self.assertIn("Move Forward", source)
        self.assertIn("localStorage", source)
        self.assertNotIn("https://", source)
        self.assertNotIn("dragstart", source)

    def test_server_cannot_bind_beyond_loopback(self) -> None:
        self.assertEqual(server.DEFAULT_CONFIG.host, "127.0.0.1")
        with self.assertRaises(ValueError):
            server.ServerConfig(host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
"""


def _kanban_icon(size: int) -> bytes:
    return _source(
        f"""
        <svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 100 100" role="img" aria-label="Local kanban board">
          <rect width="100" height="100" rx="22" fill="#312e81"/>
          <rect x="18" y="24" width="18" height="52" rx="4" fill="#c7d2fe"/>
          <rect x="41" y="24" width="18" height="38" rx="4" fill="#a5b4fc"/>
          <rect x="64" y="24" width="18" height="25" rx="4" fill="#818cf8"/>
        </svg>
        """
    )


def _kanban_readme(
    product_name: str,
    prompt: str,
    target: str,
    *,
    search_enabled: bool,
) -> bytes:
    target_note = {
        "web": "This is a local, installable browser PWA served from loopback.",
        "desktop": (
            "This is an installable PWA candidate, not a native desktop application. "
            "It has not been packaged, signed, or published to an app store."
        ),
        "mobile": (
            "This is an installable PWA candidate, not a native Android or iOS application. "
            "It has not been signed or published to a mobile app store."
        ),
    }[target]
    search_note = (
        "Use the labelled search field to filter card titles and details locally."
        if search_enabled
        else "This candidate did not request a search or filter control."
    )
    return _source(
        f"""
        # {product_name}

        {_quoted_markdown(prompt)}

        ## Target

        {target_note}

        ## Workflow

        New cards enter Backlog. Use the keyboard-operable **Move Back** and
        **Move Forward** buttons to move each card through the fixed Backlog,
        In Progress, and Done columns. Cards can also be edited or deleted.
        Drag and drop is intentionally not part of this bounded blueprint.

        ## Run locally

        ```console
        python server.py --port 8000
        ```

        Open `http://127.0.0.1:8000`. The server refuses non-loopback binds.

        ## Test

        ```console
        python -m unittest discover -s tests
        ```

        ## Data and privacy

        Cards stay in browser `localStorage`. The application has no account,
        login, telemetry, paid service, external dependency, or external network
        endpoint. Its service worker caches only same-origin application files.
        {search_note}

        The Fourfold reference binds the [Card model](model.py) and its
        [fixed-column schema](schemas/card.schema.json) to this documentation.
        """
    )


def _render_kanban_web(
    prompt: str,
    product_name: str,
    target: str,
    digest: str,
    *,
    search_enabled: bool,
) -> dict[str, bytes]:
    manifest = {
        "background_color": "#f8fafc",
        "description": prompt,
        "display": "standalone",
        "icons": [
            {"sizes": "192x192", "src": "icons/icon-192.svg", "type": "image/svg+xml"},
            {"sizes": "512x512", "src": "icons/icon-512.svg", "type": "image/svg+xml"},
        ],
        "id": "./",
        "name": product_name,
        "scope": "./",
        "short_name": product_name[:30],
        "start_url": "./",
        "theme_color": "#312e81",
    }
    config = json.dumps(
        {
            "objective": prompt,
            "productName": product_name,
            "storageKey": f"genesis-kanban-{digest[:20]}",
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    app_source = _KANBAN_APP.replace("@@CONFIG@@", config)
    service_worker = _SERVICE_WORKER.replace(
        "@@CACHE@@", f"genesis-kanban-{digest[:20]}"
    )
    repository_id = f"genesis/{_slug(product_name)}-{target}-kanban-{digest[:12]}"
    return {
        "README.md": _kanban_readme(
            product_name,
            prompt,
            target,
            search_enabled=search_enabled,
        ),
        "app.js": _source(app_source),
        "fourfold.json": _kanban_fourfold(repository_id=repository_id),
        "icons/icon-192.svg": _kanban_icon(192),
        "icons/icon-512.svg": _kanban_icon(512),
        "index.html": _source(
            _KANBAN_INDEX_HTML.replace("@@TITLE@@", html.escape(product_name, quote=True))
            .replace("@@HEADING@@", html.escape(product_name, quote=True))
            .replace(
                "@@SEARCH_CONTROL@@",
                (
                    '<div class="board-search">\n'
                    '  <label for="filter">Search cards</label>\n'
                    '  <input id="filter" type="search" '
                    'placeholder="Filter titles and details" autocomplete="off">\n'
                    '</div>'
                    if search_enabled
                    else ""
                ),
            )
        ),
        "manifest.webmanifest": _json_bytes(manifest),
        "model.py": _source(_KANBAN_MODEL),
        "schemas/card.schema.json": _json_bytes(_card_schema()),
        "server.py": _source(_LOOPBACK_SERVER),
        "service-worker.js": _source(service_worker),
        "styles.css": _source(_KANBAN_STYLES),
        "tests/test_project.py": _source(_KANBAN_TEST),
    }


def render_project(
    prompt: str,
    product_name: str,
    target: str,
    *,
    features: Sequence[str] = (),
    blueprint: str = ITEM_COLLECTION_BLUEPRINT,
) -> dict[str, bytes]:
    """Render one bounded source candidate without performing any effect.

    Args:
        prompt: The user-visible product objective retained in the candidate.
        product_name: A display name.  It never influences a filesystem path.
        target: ``web``, ``cli``, ``desktop``, or ``mobile`` (case-insensitive).
        features: Canonical admitted feature names. Unsupported feature names
            refuse instead of silently disappearing from the candidate.
        blueprint: One exact, versioned deterministic materializer profile.

    Returns:
        A path-sorted mapping of canonical POSIX-relative paths to immutable
        UTF-8 bytes.  Desktop and mobile deliberately render the same PWA
        implementation as Web, with explicit non-native disclosure.
    """

    objective = _normalise_text(prompt, "prompt", limit=_PROMPT_LIMIT, multiline=True)
    name = _normalise_text(
        product_name, "product_name", limit=_PRODUCT_LIMIT, multiline=False
    )
    selected = _normalise_target(target)
    selected_blueprint = _normalise_blueprint(blueprint)
    if selected_blueprint == KANBAN_BOARD_BLUEPRINT:
        if selected == "cli":
            raise ValueError("kanban-board-v1 does not support the CLI target")
        admitted_features = _normalise_kanban_features(features)
        search_enabled = _KANBAN_SEARCH_FEATURE in admitted_features
        digest = _kanban_identity(objective, name, selected, admitted_features)
        files = _render_kanban_web(
            objective,
            name,
            selected,
            digest,
            search_enabled=search_enabled,
        )
    else:
        admitted_features = _normalise_features(features)
        search_enabled = _SEARCH_FEATURE in admitted_features
        digest = _identity(objective, name, selected, admitted_features)
        if selected == "cli":
            files = _render_cli(
                objective,
                name,
                digest,
                search_enabled=search_enabled,
            )
        else:
            files = _render_web(
                objective,
                name,
                selected,
                digest,
                search_enabled=search_enabled,
            )
    return _safe_project(files)


__all__ = [
    "ITEM_COLLECTION_BLUEPRINT",
    "KANBAN_BOARD_BLUEPRINT",
    "render_project",
]

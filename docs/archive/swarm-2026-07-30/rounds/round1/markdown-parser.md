# Claims about `markdown-parser.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Reference definitions (`_REF_DEF`) and autolinks (`_AUTOLINK`) are matched on raw lines, not filtered by `_content_lines`, so they are parsed even inside fenced code blocks — phantom edge.
2. [risk] Inline code stripping regex `_INLINE_CODE` fails on nested backticks (e.g., `` `[[Note]]` ``) — phantom edge from wikilink inside inline code.
3. [risk] The `_INLINE_CODE` regex does not handle backtick escapes or multiple backtick sequences correctly — may miss some inline code spans.
4. [risk] No test coverage for adversarial inputs like nested brackets, pipes in aliases, or embeds inside code fences.
5. [risk] HTML comments are not stripped — a link inside `<!-- [[Note]] -->` is parsed as a real link.
6. [todo] Add unit tests for adversarial inputs: links inside fenced code, inline code, HTML comments, nested brackets, pipes in aliases, embeds.
7. [todo] Move reference definition and autolink matching inside `_content_lines` to respect code fences.
8. [todo] Fix inline code stripping to handle nested backticks and multiple backtick sequences.
9. [todo] Consider using a proper Markdown AST parser instead of regex for robustness.
10. [todo] Add HTML comment stripping before link parsing.
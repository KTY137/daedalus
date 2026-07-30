# Claims about `mcp-security.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Prompt injection through tool output: output contains instructions that alter LLM behavior; mitigation via output sanitization (strip markdown, control characters) and context isolation.
2. [risk] Rug-pull updates: server changes tool semantics after approval; mitigation via version pinning and hash verification of tool definitions.
3. [risk] Tool poisoning can cause LLM to call wrong tool; mitigation via strict schema validation and human review of tool descriptions.
4. [risk] Cross-server shadowing: multiple servers define same tool name; mitigation via unique namespacing (e.g., server_id.tool_name).
5. [todo] Enforce output sanitization: strip any text that matches prompt injection patterns (e.g., 'ignore previous instructions').
6. [todo] Implement tool definition hashing and version pinning to detect rug-pull updates.
7. [todo] Namespace tool names with server identifier to prevent cross-server shadowing.
8. [todo] Require human approval for any change to registered tool schemas.
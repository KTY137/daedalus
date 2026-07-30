# Claims about `vet-gate.py`

Produced by 2 independent review agent(s) (deepseek-chat, deepseek-v4-pro). NONE of this is verified.

1. [risk] Empty body_sha256 bypasses pin check, allowing allowance inheritance by name only
2. [risk] Homoglyph characters can bypass regex patterns (e.g., Cyrillic 'е' in 'eval')
3. [risk] Typo in vet_mcp_server causes AttributeError or incorrect severity
4. [risk] Line number drift in scan_text may mislead human reviewers
5. [todo] Fix typo: change REVIE to REVIEW in vet_mcp_server line.
6. [todo] Fix body_sha256 check to treat empty identity as no pin (do not match)
7. [todo] Add homoglyph normalization to _defang or add separate rule
8. [todo] Compute line numbers from original text, not defanged
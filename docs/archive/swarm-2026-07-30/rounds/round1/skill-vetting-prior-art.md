# Claims about `skill-vetting-prior-art.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] High false positive rates in prompt-injection detection can block legitimate plugins.
2. [risk] Dynamic sandboxing may be evaded by time-based or environment-aware triggers.
3. [risk] Static analysis alone misses zero-day and obfuscated threats.
4. [risk] Metadata can be adversarially crafted to bypass NLP filters.
5. [todo] Implement static analysis with signature and ML-based detection for known vulnerabilities and prompt injection.
6. [todo] Monitor plugin behavior post-installation for drift or delayed malicious actions.
7. [todo] Regularly update detection models with new attack patterns from the literature.
8. [todo] Add dynamic sandbox execution for all plugins before granting permissions.
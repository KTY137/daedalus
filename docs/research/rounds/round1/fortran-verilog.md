# Claims about `fortran-verilog.py`

Produced by 1 independent review agent(s) (deepseek-chat). NONE of this is verified.

1. [risk] Yosys is primarily for synthesis, not just parsing; its dependency graph extraction may require additional passes.
2. [risk] Verible's AST may not cover all SystemVerilog constructs (e.g., some assertions); sv-parser is less mature.
3. [risk] fparser may not handle all Fortran 2008/2018 features; LFortran is not yet production-ready.
4. [todo] Evaluate fparser's ability to parse target Fortran codebase (e.g., test with modern Fortran features).
5. [todo] Consider Yosys for hierarchical module extraction if synthesis-level analysis is needed.
6. [todo] Evaluate Verible's AST for extracting module instantiations and `include dependencies.
7. [todo] Define a common JSON schema for module/dependency graphs across both languages.
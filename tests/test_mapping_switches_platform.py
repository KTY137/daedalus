"""OS-owned names stay out of both halves of switch documentation drift."""
from pathlib import Path

import pytest

from daedalus.mapping import switches


@pytest.mark.parametrize("name", ["USER", "USERDOMAIN", "PROCESSOR_IDENTIFIER", "PATH"])
@pytest.mark.parametrize("doc_style", ["absent", "bare", "operator"])
def test_platform_read_does_not_become_either_kind_of_drift(tmp_path: Path, name, doc_style):
    package = tmp_path / "daedalus"
    package.mkdir()
    (package / "identity.py").write_text(
        f'import os\nIDENTITY = os.environ.get("{name}")\n'
        'DARK = os.environ.get("DAEDALUS_UNDOCUMENTED_TEST")\n',
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    text = (
        "No environment configuration is documented." if doc_style == "absent"
        else name if doc_style == "bare"
        else f"The environment variable `{name}` identifies the host."
    )
    (docs / "host.md").write_text(text, encoding="utf-8")
    report = switches.analyse(tmp_path)
    assert any(item.name == name for item in report.env_switches)
    assert all(name not in (item.read, item.documented) for item in report.drift)
    assert any(item.read == "DAEDALUS_UNDOCUMENTED_TEST" for item in report.drift)


def test_an_os_variable_mentioned_only_in_docs_is_not_a_daedalus_switch(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "host.md").write_text("Set environment variable `PROCESSOR_IDENTIFIER`.\n", encoding="utf-8")
    assert switches.analyse(tmp_path).drift == ()

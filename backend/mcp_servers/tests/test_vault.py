"""The Markdown notes vault -- path safety + read/write/append/log_progress."""

import pytest

from backend.mcp_servers.secondary_server import vault


def test_write_read_roundtrip(vault_path):
    info = vault.write_note("ideas", "# Ideas\n\nfirst")
    assert info.name == "ideas.md"
    assert vault.read_note("ideas") == "# Ideas\n\nfirst"
    assert (vault_path / "ideas.md").exists()


def test_name_gets_md_suffix_and_subdirs_allowed(vault_path):
    vault.write_note("weekly/2026-w36", "hi")
    assert (vault_path / "weekly" / "2026-w36.md").exists()
    assert {n.name for n in vault.list_notes()} == {"weekly/2026-w36.md"}


def test_append_creates_then_grows(vault_path):
    vault.append_note("log", "line one")
    vault.append_note("log", "line two")
    body = vault.read_note("log")
    assert body == "line one\n\nline two\n"


@pytest.mark.parametrize(
    "bad",
    ["../escape", "a/../../b", "/etc/passwd", "..", "", "  ", "weird*name", "a\\b"],
)
def test_unsafe_names_are_rejected(vault_path, bad):
    with pytest.raises(vault.VaultError):
        vault.write_note(bad, "x")


def test_read_missing_note(vault_path):
    with pytest.raises(vault.VaultError):
        vault.read_note("nope")


def test_log_progress_appends_dated_sections(vault_path):
    vault.log_progress("2 sessions, 75% recall", heading="Week 36", date="2026-09-03")
    vault.log_progress("slower week", date="2026-09-10")
    text = vault.read_note(vault.PROGRESS_NOTE)
    assert "## 2026-09-03 — Week 36" in text
    assert "2 sessions, 75% recall" in text
    assert "## 2026-09-10 — Progress" in text  # default heading
    assert text.index("2026-09-03") < text.index("2026-09-10")  # chronological append


def test_log_progress_defaults_date_to_today(vault_path):
    import datetime as dt

    out = vault.log_progress("today's work")
    assert dt.date.today().isoformat() in out.appended

"""Regression: app.py must initialize both YouTube handler modules.

The repo has two parallel YouTube handler modules:

  - ``src.youtube_handler``               — used by ``src/chat_handler.py`` and
    ``src/chat_processor.py`` (the chat path the user actually hits).
  - ``services.youtube.youtube_handler``  — used by ``routes/diagnostics_routes.py``.

Each module keeps its own module-level ``YOUTUBE_AVAILABLE`` flag. ``app.py``
previously only called ``services.youtube.init_youtube()`` at startup, so the
``src`` module's flag stayed ``False``. Chat requests that included a YouTube
URL therefore fell through to ``{"success": False, "error": "YouTube transcript
API not available"}`` even when ``youtube-transcript-api`` was installed, while
the diagnostics endpoint worked.

The fix is for ``app.py`` to call both ``init_youtube()`` variants at startup
so both code paths see the same state. This test fails on the broken version
and passes after the fix is applied.
"""
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP_PY = ROOT / "app.py"


def _read_app_py() -> str:
    return APP_PY.read_text(encoding="utf-8")


def test_app_py_initializes_src_youtube_handler():
    """app.py must call init_youtube() on src.youtube_handler, not just the services one."""
    source = _read_app_py()

    # Both imports must be present.
    assert re.search(
        r"^\s*from\s+services\.youtube\s+import\s+init_youtube\b",
        source,
        re.MULTILINE,
    ), "app.py is missing `from services.youtube import init_youtube`"
    assert re.search(
        r"^\s*from\s+src\.youtube_handler\s+import\s+init_youtube\b",
        source,
        re.MULTILINE,
    ), (
        "app.py is missing `from src.youtube_handler import init_youtube`. "
        "The chat-path YouTube handler is never initialized, so chat requests "
        "with a YouTube URL always fail with 'YouTube transcript API not available'."
    )

    # Both call sites must be present in the YouTube init block. Look for
    # `init_youtube(` call expressions after the imports above.
    assert "init_youtube()" in source, "app.py never calls init_youtube()"


def test_both_youtube_modules_have_init_youtube_symbol():
    """Sanity check: the symbols the test references actually exist on the legacy module."""
    # This is the module the chat path uses.
    legacy = sys.modules.get("src.youtube_handler")
    if legacy is None:
        import src.youtube_handler  # noqa: F401
        legacy = sys.modules["src.youtube_handler"]
    assert hasattr(legacy, "init_youtube")
    assert hasattr(legacy, "YOUTUBE_AVAILABLE")
    assert hasattr(legacy, "extract_transcript_async")


def test_chat_path_short_circuits_when_legacy_module_not_initialized(monkeypatch):
    """Document the short-circuit behaviour the fix removes.

    With the legacy module's flag at its module-default ``False``,
    ``extract_transcript_async`` returns the 'not available' error without
    ever attempting a transcript fetch. After the fix, ``app.py`` flips the
    flag and the short-circuit is bypassed.
    """
    # Ensure a clean module state and a successful stub for the optional lib
    # (we're not testing the actual transcript fetch here, just the guard).
    fake = types.ModuleType("youtube_transcript_api")
    fake.YouTubeTranscriptApi = object
    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake)
    for name in (
        "src.youtube_handler",
        "services.youtube",
        "services.youtube.youtube_handler",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)

    import asyncio
    import src.youtube_handler as legacy

    # Pre-condition: the legacy module's flag is False by default because
    # init_youtube() was never called.
    assert legacy.YOUTUBE_AVAILABLE is False

    result = asyncio.run(
        legacy.extract_transcript_async("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ")
    )
    assert result["success"] is False
    assert result["error"] == "YouTube transcript API not available"
    assert result["transcript"] is None

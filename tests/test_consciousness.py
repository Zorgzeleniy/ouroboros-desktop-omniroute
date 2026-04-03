"""
Tests for BackgroundConsciousness._emit_progress.

Verifies events have the correct shape, reach the queue,
and respect pause / chat_id=None semantics.

Run: pytest tests/test_consciousness.py -v
"""

import json
import os
import pathlib
import queue
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestEmitProgress(unittest.TestCase):
    """Tests for BackgroundConsciousness._emit_progress."""

    def _make_consciousness(self, chat_id=42, event_queue=None):
        """Create a BackgroundConsciousness with mocked dependencies."""
        from ouroboros.consciousness import BackgroundConsciousness

        tmpdir = tempfile.mkdtemp()
        drive_root = pathlib.Path(tmpdir)
        (drive_root / "logs").mkdir(parents=True, exist_ok=True)
        repo_dir = pathlib.Path(tmpdir) / "repo"
        repo_dir.mkdir()

        eq = event_queue if event_queue is not None else queue.Queue()

        with patch.object(BackgroundConsciousness, '_build_registry', return_value=MagicMock()):
            bc = BackgroundConsciousness(
                drive_root=drive_root,
                repo_dir=repo_dir,
                event_queue=eq,
                owner_chat_id_fn=lambda: chat_id,
            )
        return bc, eq, drive_root

    def test_event_shape(self):
        """Event has type, chat_id, text, is_progress, ts."""
        bc, eq, _ = self._make_consciousness(chat_id=99)
        bc._emit_progress("thinking about things")
        evt = eq.get_nowait()

        self.assertEqual(evt["type"], "send_message")
        self.assertEqual(evt["chat_id"], 99)
        self.assertEqual(evt["text"], "💬 thinking about things")
        self.assertEqual(evt["format"], "markdown")
        self.assertTrue(evt["is_progress"])
        self.assertIn("ts", evt)

    def test_event_reaches_queue(self):
        """Event actually ends up in the queue (not silently dropped)."""
        bc, eq, _ = self._make_consciousness()
        bc._emit_progress("hello world")
        self.assertFalse(eq.empty())

    def test_empty_content_skipped(self):
        """Empty or whitespace-only content produces no event."""
        bc, eq, drive_root = self._make_consciousness()
        progress_path = drive_root / "logs" / "progress.jsonl"

        bc._emit_progress("")
        bc._emit_progress("   ")
        bc._emit_progress(None)

        self.assertTrue(eq.empty())
        # Also should not persist to file
        self.assertFalse(progress_path.exists())

    def test_chat_id_none_skips_queue_but_persists(self):
        """When chat_id is None, event is NOT queued but IS persisted."""
        bc, eq, drive_root = self._make_consciousness(chat_id=None)
        bc._emit_progress("background thought")

        # Queue should be empty
        self.assertTrue(eq.empty())

        # File should have the entry
        progress_path = drive_root / "logs" / "progress.jsonl"
        self.assertTrue(progress_path.exists())
        entry = json.loads(progress_path.read_text().strip())
        self.assertEqual(entry["type"], "send_message")
        self.assertEqual(entry["content"], "background thought")
        self.assertTrue(entry["is_progress"])

    def test_paused_events_go_to_deferred(self):
        """When paused, events go to _deferred_events, not the queue."""
        bc, eq, _ = self._make_consciousness()
        bc._paused = True
        bc._emit_progress("deferred thought")

        self.assertTrue(eq.empty())
        self.assertEqual(len(bc._deferred_events), 1)
        self.assertEqual(bc._deferred_events[0]["type"], "send_message")
        self.assertEqual(bc._deferred_events[0]["text"], "💬 deferred thought")


if __name__ == "__main__":
    unittest.main()

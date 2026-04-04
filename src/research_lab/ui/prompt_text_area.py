"""Multiline prompt widget with auto-expanding height and Claude Code-like UX.

Enter submits; Shift+Enter (or Ctrl+J) inserts a newline.  Arrow keys,
backspace, delete, clipboard, and undo all work across lines via Textual's
built-in TextArea bindings.
"""

from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import TextArea


class PromptSubmitted(Message):
    """Posted when the user presses Enter to submit the prompt buffer."""

    def __init__(self, sender: PromptTextArea) -> None:
        self.sender = sender
        super().__init__()


class PromptTextArea(TextArea):
    """Enter submits; Shift+Enter / Ctrl+J inserts a newline.

    The widget auto-expands vertically (up to *MAX_LINES*) as the user
    types more lines, then shrinks back when text is cleared.
    """

    MAX_LINES = 10
    NEWLINE_KEYS = frozenset({"shift+enter", "ctrl+j"})

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        if key in self.NEWLINE_KEYS:
            self.insert("\n")
            event.stop()
            event.prevent_default()
            self._adjust_height()
            return
        if key == "enter":
            self.post_message(PromptSubmitted(self))
            event.stop()
            event.prevent_default()
            return
        await super()._on_key(event)
        self._adjust_height()

    def on_mount(self) -> None:
        self._adjust_height()

    def watch_text(self, value: str) -> None:
        self._adjust_height()

    def _adjust_height(self) -> None:
        """Resize self and the parent container to fit content."""
        lines = max(1, self.document.line_count)
        desired = min(lines, self.MAX_LINES)
        self.styles.height = desired
        if self.parent is not None:
            self.parent.styles.height = desired + 2

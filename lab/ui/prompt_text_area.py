"""Multiline prompt widget with auto-expanding height.

Enter submits the buffer; Tab inserts a newline (Tab does not move focus while the
prompt is focused).

Arrow keys, backspace, delete, clipboard, and undo work across lines via Textual's
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
    """Enter submits; Tab inserts a newline."""

    # Keep in sync with #prompt-box max-height (leave room for border/padding).
    MAX_LINES = 12

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        # Tab and Ctrl+I are the same physical key in common TTY mappings.
        if key == "tab" or key == "ctrl+i":
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

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Keep height in sync after edits that do not go through our ``_on_key`` path."""
        if event.text_area is self:
            self._adjust_height()

    def on_mount(self) -> None:
        self._adjust_height()

    def on_resize(self, event: events.Resize) -> None:
        self._adjust_height()

    def watch_text(self, value: str) -> None:
        self._adjust_height()

    def _adjust_height(self) -> None:
        """Resize self and the parent container to fit content."""
        if self.soft_wrap and self.is_mounted and self.wrap_width > 0:
            # Re-wrap so ``wrapped_document.height`` matches the current buffer (e.g. after
            # deleting a newline); otherwise height can stay stale until the cursor moves.
            self.wrapped_document.wrap(self.wrap_width, self.indent_width)
            lines = max(1, self.wrapped_document.height)
        else:
            lines = max(1, self.document.line_count)
        desired = min(lines, self.MAX_LINES)
        self.styles.height = desired
        if self.parent is not None:
            self.parent.styles.height = desired + 2

"""PromptTextArea newline-on-Tab behavior."""

import pytest
from textual import events

from lab.ui.prompt_text_area import PromptTextArea


class _RecordingPrompt(PromptTextArea):
    def __init__(self) -> None:
        super().__init__("")
        self.recorded: list[str] = []

    def insert(self, text: str) -> None:  # type: ignore[override]
        self.recorded.append(text)


@pytest.mark.asyncio
async def test_tab_and_ctrl_i_insert_newline() -> None:
    w = _RecordingPrompt()
    await w._on_key(events.Key("tab", None))
    await w._on_key(events.Key("ctrl+i", None))
    assert w.recorded == ["\n", "\n"]

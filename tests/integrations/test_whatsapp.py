"""Representative test for WhatsApp's propose-tool queuing logic — pure DB
logic, no browser needed. The browser-automation paths (login, list/read
chats, actually sending) are inherently live-only; see the plan doc's
verification section for why they can't be driven from a sandboxed shell.
"""

import pytest

from edith.integrations import whatsapp
from edith.memory.records import system
from edith.memory.storage import sqlite
from edith.tools.base import ToolContext
from edith.tools.registry import ToolRegistry


@pytest.fixture
def conn(tmp_path):
    c = sqlite.connect(tmp_path / "test.db")
    yield c
    c.close()


def test_send_whatsapp_message_propose_queues_pending_action(conn):
    registry = ToolRegistry(ToolContext(conn=conn))
    registry.register_module(whatsapp)

    result = registry.dispatch("send_whatsapp_message", {"chat_name": "Mom", "message": "hi there"})

    assert "Queued as action #" in result
    pending = system.get_pending_actions(conn)
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "send_whatsapp_message"
    assert pending[0]["args"] == {"chat_name": "Mom", "message": "hi there"}


def test_execute_send_whatsapp_message_is_in_executors():
    assert "send_whatsapp_message" in whatsapp.EXECUTORS
    assert whatsapp.EXECUTORS["send_whatsapp_message"] is whatsapp.execute_send_whatsapp_message

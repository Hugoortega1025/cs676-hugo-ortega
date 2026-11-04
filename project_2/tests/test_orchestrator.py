"""
Tests for the tool-use router in orchestrator.py.

Every test uses ScriptedToolLLM, a fake model that replays scripted replies,
so they run offline, instantly, and for free.
"""

from personaforge.llm import DemoLLM, ScriptedToolLLM
from personaforge.orchestrator import MAX_TOOL_ROUNDS, Orchestrator


# Shortcuts for building the replies the fake model plays back.
def tool_request(name, tool_input, request_id="t1"):
    """One round where Claude asks for a single tool."""
    return {
        "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": request_id, "name": name, "input": tool_input}],
    }


def text_reply(text):
    """One round where Claude is done and just talks."""
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}


# A sentence the regex router failed on now creates a persona.
def test_tool_use_creates_a_persona(tmp_path):
    llm = ScriptedToolLLM(responses=[
        tool_request("create_persona", {"description": "a calm nurse"}),
        text_reply("Done, I created a nurse."),
    ])
    orch = Orchestrator(llm, persona_dir=tmp_path)

    result = orch.handle("I want a nurse character")

    assert result.reply == "Done, I created a nurse."
    assert len(list(tmp_path.glob("*.md"))) == 1
    assert len(llm.tool_calls) == 2


# Two requests in one round should make two personas.
def test_several_tools_in_one_round(tmp_path):
    two_requests = {
        "stop_reason": "tool_use",
        "content": [
            {"type": "tool_use", "id": "t1", "name": "create_persona", "input": {"description": "a calm nurse"}},
            {"type": "tool_use", "id": "t2", "name": "create_persona", "input": {"description": "a demanding personal trainer"}},
        ],
    }
    llm = ScriptedToolLLM(responses=[two_requests, text_reply("Created both.")])
    orch = Orchestrator(llm, persona_dir=tmp_path)

    orch.handle("make a nurse and a personal trainer")

    assert len(list(tmp_path.glob("*.md"))) == 2


# When Claude asks a question instead of using a tool,
# that question is the reply and no persona gets created.
def test_clarifying_question(tmp_path):
    llm = ScriptedToolLLM(responses=[
        text_reply("What kind of person should they be?"),
    ])
    orch = Orchestrator(llm, persona_dir=tmp_path)

    result = orch.handle("create a persona")

    assert result.reply == "What kind of person should they be?"
    assert len(list(tmp_path.glob("*.md"))) == 0
    assert len(llm.tool_calls) == 1



# If Claude never stops asking for tools, the loop gives up after MAX_TOOL_ROUNDS.
def test_stops_after_max_rounds(tmp_path):
    llm = ScriptedToolLLM(responses=[tool_request("list_personas", {})])
    orch = Orchestrator(llm, persona_dir=tmp_path)

    result = orch.handle("list personas")

    assert "too many steps" in result.reply
    assert len(llm.tool_calls) == MAX_TOOL_ROUNDS


# Asking for 50 turns gets capped at 14.
def test_turns_are_capped(tmp_path):
    llm = ScriptedToolLLM(responses=[
        tool_request("start_conversation", {"topic": "cancelling a membership", "turns": 50}),
        text_reply("They talked."),
    ])
    orch = Orchestrator(llm, persona_dir=tmp_path)
    orch._create_persona("a gym member thinking of cancelling")
    orch._create_persona("a personal trainer")

    result = orch.handle("have them talk for a long time")

    assert result.conversation is not None
    assert len(result.conversation.turns) == 14


# A tool that isn't on the menu doesn't crash, and the error goes back to Claude.
def test_unknown_tool_is_reported_back(tmp_path):
    llm = ScriptedToolLLM(responses=[
        tool_request("delete_persona", {"name": "anyone"}),
        text_reply("Sorry, I can't delete personas."),
    ])
    orch = Orchestrator(llm, persona_dir=tmp_path)

    result = orch.handle("delete everyone")

    assert result.reply == "Sorry, I can't delete personas."
    result_sent_to_claude = llm.tool_calls[1]["messages"][-1]["content"][0]["content"]
    assert "I don't have a tool called 'delete_persona'" in result_sent_to_claude


# A model without complete_with_tools (offline mode) still uses the old regex router.
def test_offline_mode_uses_regex_router(tmp_path):
    orch = Orchestrator(DemoLLM(), persona_dir=tmp_path)

    orch.handle("create a persona doctor")

    assert len(list(tmp_path.glob("*.md"))) == 1
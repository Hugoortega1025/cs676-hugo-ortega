## Baseline tests (regex router, offline) — Nov 2

| What I typed | Expected | What happened | Why |
|---|---|---|---|
| create a persona | asks what kind | canned sentence | hard-coded empty check, not a real question |
| make two doctors and a nurse | creates 3 personas | stub reply | no word "persona", regex misses |
| list the personas then have them talk about diet | list, then talk | only listed | first regex match wins |
| I want a nurse character | creates a nurse | stub reply | no word "persona", regex misses |

Other: "Unnamed (unknown)" persona in temp/ = parser fallback. "With Chronic Back Pain" got role "with" = regex grabs the
first word of the description as the role.

## Nov 2 — Added the TOOLS menu (orchestrator.py)

What: wrote TOOLS, the list of 3 tools Claude can choose from:
create_persona, list_personas, start_conversation. Nothing uses it yet.
Tests: still 41 passed.

Decisions:
- create_persona says "call it once per character" so "two doctors and a
  nurse" becomes 3 separate personas, not one mashed-together one.
- participants is a list of names, not one string, so the code doesn't
  have to split "Mike and Sam" itself.
- turns description matches what the code can actually do (fixed number,
  default 6). One turn = one line = one API call.

Ideas for later:
- Let a conversation stop early once the question is answered (README task #3).
- Cap turns so Claude can't ask for 200 (cost + robustness).


## Nov 3 — Added complete_with_tools() to ClaudeLLM (llm.py)

What: a second version of complete() that sends Claude the TOOLS menu and
keeps every piece of its reply. Tests: still 41 passed.

Decisions:
- Kept complete() unchanged. Personas and conversations only need text, so
  they keep using it. Only the router will use the new method.
- Returns plain dictionaries instead of Anthropic's own objects, so a fake
  model in tests can return the same shape without the SDK.
- Only the real model (ClaudeLLM) has it. Offline mode doesn't, which will let
  the router fall back to regex when there's no tool support.


## Nov 4 — Tool-use loop (orchestrator.py)

What: added _handle_with_tools, the loop that lets Claude pick tools and runs them,
plus _ROUTER_SYSTEM and MAX_TOOL_ROUNDS. handle() now uses it when the model
supports tools, and falls back to the old regex router when it doesn't.

Decisions:
- New router prompt tells Claude to ask a question when info is missing (fixes task #2).
- Cap of 5 rounds so it can't loop forever.
- Kept the regex router as offline fallback and baseline.

## Nov 4 — Tests for the tool-use loop

What: added ScriptedToolLLM (a fake model that replays scripted tool requests) and
tests/test_orchestrator.py with 7 tests. 48 passed.

Why a fake: real Claude costs money, answers differently each run, and the grader
may not have a key.

Covers: creating from a phrase regex failed on, several tools in one round,
clarifying question, 5-round safety net, 14-turn cap, unknown tool, offline fallback.
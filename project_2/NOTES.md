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


## Nov 4 — First live run (tool use, claude-haiku-4-5)

Ran the same 4 baseline sentences with the real model.

| What I typed | Regex router (offline) | Tool use (live) |
|---|---|---|
| create a persona | canned sentence | asked what kind of character, with examples (cheerful barista, etc.) |
| make two doctors and a nurse | stub reply, nothing made | made 3 personas, 3 files. Made up their details itself without asking me |
| list the personas then have them talk about diet | only listed | did both, but I never saw the list, and the conversation broke down (below) |
| I want a nurse character | stub reply | asked what kind of nurse (compassionate, gruff, burned out...) |

What worked:
- Clarifying questions now come from Claude instead of a hard-coded line.
- "Two doctors and a nurse" became 3 separate personas (once-per-character works).
- Claude picked the 3 relevant personas for the conversation out of 7 in temp/
  (4 were old offline demo leftovers). Regex would have just grabbed the first 2.

Problems:
- Inconsistent clarifying: it asked about "a nurse character" but not about
  "two doctors and a nurse," even though both are just as vague. It's the
  model's judgment, not a rule in my code.
- The list never showed on screen. Tool results go back to Claude, and only
  Claude's final text + events get shown. Need to fix.
- The conversation broke character. The agents were confused about who they
  were talking to ("I can't play Dr. Marcus Chen," "who are you?"), kept
  telling each other they could only play themselves, and only got into an
  actual scene near the end. Possible causes: each agent sees the others' lines
  as a "user" talking to it, the topic ("diet") had no situation to anchor it,
  and it was 3 people when the code was built for 2. Need to check
  conversation.py and agent.py.
- Similar names (Dr. Eleanor Chen, Dr. Marcus Chen, Nurse Marcus Webb) could
  confuse find_persona if someone asks for "Marcus."

Saved transcript: transcripts/nov4-diet-three-personas-haiku.md


## Nov 4 — Fixed the list display and the broken conversation

What:
- The persona list now shows on screen. Before, it only went back to Claude, so
  I never saw it unless Claude repeated it.
- Each agent is now told the situation and who else is in the room (name, role,
  summary). This goes in the agent's instructions (system prompt).
- Removed the fake "Scene" speaker. It sent the topic as a message like
  "Scene: diet", and the agents thought a person was talking to them.
- Changed the topic description in TOOLS so Claude sends a real situation
  ("a follow-up appointment where the patient wants to cut carbs"), not one word.
- Tests: 50 passed. Added tests for the list showing on screen and for agents
  knowing the scene.

Why:
- In the first live run the agents spent most of the conversation confused
  ("I can't play Dr. Marcus Chen," "who are you?"). Reading agent.py showed they
  were never told who else was there, and the first thing they got was "Scene: diet".

Changed a provided test:
- test_topic_reaches_the_agents checked for the topic in the messages, where the
  old Scene speaker put it. The topic is in the system prompt now, so the test
  checks there instead. It still checks the same thing: the topic reaches the agents.


Next: rerun the same request live and compare it to the first transcript.


## Nov 6 — Live rerun found 2 new bugs

Ran "make two doctors and a nurse", then "have them talk about diet", then
"make two personal trainers and a client".

Bug 1: personas with the same name overwrite each other.
- It made two doctors both named Dr. Marcus Chen, and later two people named
  Marcus Chen. Same name = same filename, so the second one replaced the first.
- It said it created 6 personas. ls temp/ shows only 4 files.
- Why: save_persona writes the file without checking if it already exists
  (persona.py YOUR TASK #2). Haiku also keeps reusing the same names
  ("Marcus", "Chen"), because each persona is written in its own call that
  doesn't know which names are taken.

Bug 2: the router forgets what happened one message ago.
- After creating 3 personas, "have them talk about diet" got back
  "Do you already have personas created?"
- Why: every message starts a brand-new transcript in _handle_with_tools, so
  Claude has no idea it just made anyone, and "them" means nothing
  (orchestrator.py YOUR TASK #6). It didn't show up in the first live run
  because that one did both steps in one sentence.



Next: fix the overwrite (add -2, -3 to the filename, and tell the writer which
names are taken), then give the router short-term memory.


## Nov 7 — Fixed the 2 bugs from the Nov 6 live run

Fix 1: no more overwriting.
- save_persona now checks if the filename is taken. If marcus-chen.md exists,
  the next one is saved as marcus-chen-2.md instead of replacing it.
- The -2 is only on the filename. The persona inside is still "Marcus Chen".

Fix 2: fewer repeated names.
- Each persona is written in its own call to Claude, so it couldn't see which
  names were already used. Now we pass it the names already saved in temp/
  and tell it to pick a different one.
- This is a request, not a guarantee. Fix 1 is the safety net:
  the prompt asks, the code makes sure nothing gets lost.

Fix 3: the router remembers.
- "make two doctors and a nurse" then "have them talk" (two separate messages)
  used to fail, because every message started from scratch.
- Now it remembers the last 10 messages (5 back-and-forths), text only, and is
  told which personas exist every time.
- Kept to 10 so every request doesn't resend the whole session, which would get
  expensive.
- Only plain text is remembered, not the tool requests, because those have to
  stay in matching pairs, and trimming could cut a pair in half.

Tests: 55 passed. New tests for no overwriting, taken names reaching the
writer, memory working across messages, personas being listed, and memory
staying capped.


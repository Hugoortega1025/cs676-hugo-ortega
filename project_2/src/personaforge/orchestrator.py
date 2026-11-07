"""
orchestrator.py — the agent you talk to.

You type "I want to create a persona patient" and something has to decide that
you meant `create_persona("patient")`. That decision is intent routing, and it
happens here.

The baseline router is regular expressions. It works, it is free, it is
deterministic, and it is obviously not what a modern agent does — a real one
would hand Claude a set of tools and let the model choose. Replacing this router
with genuine tool use is the headline task of this project, and the tool schemas
you would need are sketched at the bottom of this file.

Anything the router does *not* recognize is passed to the model as ordinary
conversation, so the orchestrator still feels like something you are talking to
rather than a command prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .agent import agent_from_spec
from .conversation import Conversation, Turn, run_conversation, save_transcript
from .llm import LLM
from .persona import (
    DEFAULT_PERSONA_DIR,
    PersonaSpec,
    find_persona,
    generate_persona,
    list_personas,
    save_persona,
)

TOOLS = [
            {
                "name": "create_persona",
                "description": "Create and save a new persona character. Call it once per character made.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string",
                                        "description": "What kind of person to create, for example, 'a personal trainer who is demanding and motivating'"},
                    },
                    "required": ["description"],
                },
            },
            {"name": "list_personas", 
             "description": "List all personas that have been created so far.",
             "input_schema" : {
                 "type": "object",
                 "properties" : {},
                 },
             },
            {"name": "start_conversation", 
             "description": "Start a conversation between two or more existing personas about a topic",
               "input_schema": {
                   "type" : "object",
                   "properties" : {
                       "topic" : {
                           "type" : "string",
                            "description": "The situation the personas are in, as a short scene, for example, 'a follow-up appointment where the patient wants to cut carbs'. Not a single word.",

                       },
                       "participants" : {
                           "type" : "array", 
                           "items": {"type":"string"},
                           "description": "A list of persona names involved in the conversation",
                       },
                       "turns" : {
                           "type" : "integer",
                            "description" : "Total number of lines spoken across all participants. Defaults to 6.",
                            },
                   },
                   "required": ["topic"],
               },
            }, 
        ]


_STAGE_MANAGER_SYSTEM = """You are the stage manager of a persona simulation workshop.

The user builds fictional characters and has them talk to each other. You help them
decide who to create and what those characters should discuss.

Be brief — two or three sentences. When the user seems ready to act, remind them they
can say things like "create a persona doctor", "list personas", or "have them talk
about the test results"."""


_ROUTER_SYSTEM = """You are the stage manager of a persona simulation workshop.

The user builds fictional characters and has them talk to each other. Use the tools to create
personas, list them, and start conversations. If a request is missing something you need,
such as what kind of character to create, ask the user a short clarifying question to avoid guessing.
Keep replies brief - two or three sentences.

"""
# This makes sure the model doesn't loop forever
MAX_TOOL_ROUNDS = 5     


# Short amount of back-and-forth messages the router remembers.
# Will allow Claude to remember the personas present in the conversation
MAX_REMEMBERED_MESSAGES = 10

@dataclass
class Result:
    """What the orchestrator did, in a form the UI can render."""

    reply: str
    events: List[str] = field(default_factory=list)
    conversation: Optional[Conversation] = None


class Orchestrator:
    """Routes what the user typed to the right part of the package."""

    def __init__(self, llm: LLM, persona_dir: Path = DEFAULT_PERSONA_DIR) -> None:
        self.llm = llm
        self.persona_dir = Path(persona_dir)
        self.history: List[dict] = []
        self.router_history: List[dict] = []    # Recent exchanges the router remembers

    # -- intents ------------------------------------------------------------

    def _create_persona(self, description: str) -> Result:
        """Author a persona, write it to disk, and report where it landed."""
        if not description.strip():
            return Result(reply="Tell me what kind of persona — for example, 'create a persona doctor'.")

        # Names already on disk, so the new persona gets a different one
        taken = [s.name for s in list_personas(self.persona_dir)]
        spec = generate_persona(description, self.llm, taken_names=taken)
        path = save_persona(spec, self.persona_dir)
        return Result(
            reply=f"Created **{spec.name}** ({spec.role}) — {spec.summary}",
            events=[f"wrote {path}"],
        )

    def _list_personas(self) -> Result:
        """Show what is currently in the persona folder."""
        specs = list_personas(self.persona_dir)
        if not specs:
            return Result(reply="No personas yet. Try: create a persona patient")

        lines = [f"- **{s.name}** ({s.role}) — {s.summary}" for s in specs]
        return Result(reply=f"{len(specs)} persona(s) in `{self.persona_dir}`:\n" + "\n".join(lines))

    def _converse(
        self,
        topic: str,
        who: Optional[List[str]] = None,
        turns: int = 6,
        on_turn: Optional[Callable[[Turn], None]] = None,
        on_start: Optional[Callable[[str], None]] = None,
    ) -> Result:
        """Wake up two personas and let them talk."""
        specs: List[PersonaSpec] = []

        if who:
            for name in who:
                found = find_persona(name, self.persona_dir)
                if found is None:
                    return Result(reply=f"I couldn't find a persona matching '{name}'.")
                specs.append(found)
        else:
            specs = list_personas(self.persona_dir)[:2]

        if len(specs) < 2:
            return Result(reply="I need at least two personas before they can talk. Create another one first.")

        agents = [agent_from_spec(s, self.llm) for s in specs]
        if on_start is not None:
            on_start(topic)
        conversation = run_conversation(agents, topic=topic, turns=turns, on_turn=on_turn)
        path = save_transcript(conversation, self.persona_dir, filename="conversation.md")

        return Result(
            reply=f"{len(conversation.turns)} turns between {' and '.join(s.name for s in specs)}.",
            events=[f"wrote {path}"],
            conversation=conversation,
        )

    def _chat(self, text: str) -> Result:
        """Nothing matched, so just talk to the user."""
        self.history.append({"role": "user", "content": text})
        reply = self.llm.complete(_STAGE_MANAGER_SYSTEM, self.history, max_tokens=512)
        self.history.append({"role": "assistant", "content": reply})
        return Result(reply=reply)


    def _run_tool(
            self,
            tool_name: str,
            tool_input: dict,
            on_turn: Optional[Callable[[Turn], None]] = None,
            on_start: Optional[Callable[[str], None]] = None,
    ) -> Result:
        """
        Run the method that matches the tool Claude asked for.
        This method takes the tool name and inputs that Claude filled in,
        and calls the matching method that actually does the work.
        
        """

        # Claude requested a new persona; hand over the description it filled in
        if tool_name == "create_persona":    
            return self._create_persona(tool_input.get("description", ""))

        # Claude wants to see every persona made in temp/
        elif tool_name == "list_personas":
            return self._list_personas()

        # Claude requested personas to start the conversation: Defaults to 6 lines, capped at 14
        elif tool_name == "start_conversation":
            turns = min(tool_input.get("turns", 6), 14)  
            return self._converse(
                topic=tool_input.get("topic", "an initial consultation"),
                who=tool_input.get("participants"),
                turns=turns,
                on_turn=on_turn,
                on_start=on_start,
            )

       #Claude requested for a tool that isn't on the tool menu 
        return Result(reply=f"I don't have a tool called '{tool_name}'.")

    # -- routing ------------------------------------------------------------

    def handle(
        self,
        text: str,
        on_turn: Optional[Callable[[Turn], None]] = None,
        on_start: Optional[Callable[[str], None]] = None,
    ) -> Result:
        """
        Work out what the user meant and do it.

        Uses tool use when the model supports it, and falls back to the old regex
        router when it doesn't (offline mode and tests).
        """

        if not hasattr(self.llm, "complete_with_tools"):
            return self._handle_regex(text, on_turn = on_turn, on_start = on_start)

        
    
        return self._handle_with_tools(text, on_turn = on_turn, on_start = on_start)


    def _handle_with_tools(
        self,
        text: str,
        on_turn: Optional[Callable[[Turn], None]] = None,
        on_start: Optional[Callable[[str], None]] = None,
    ) -> Result:            
        """
        Let Claude pick tools, run them, and send the results back until it is done.

        Claude only chooses which tool to use. This method runs them, using the phone line (complete_with_tools) once per round.
        """

    
        # Uses what the router remembers and then adds the transcript of the exchange for Claude
        messages = self.router_history + [{"role": "user", "content": text}]

        # Tells Claude which personas exist
        existing = [f"{s.name} ({s.role})" for s in list_personas(self.persona_dir)]
        if existing:
            system = _ROUTER_SYSTEM + "\n\nPersonas that already exist: " + ", ".join(existing)
        else:
            system = _ROUTER_SYSTEM + "\n\nNo personas exist yet."
        
        # Events for the screen such as 'wrote temp/nurse-hugo.md
        events : List[str] = []
        
        
        conversation = None

        # MAX_TOOL_ROUNDS is capped at 5, so a confused Claude cant loop forever
        for _ in range(MAX_TOOL_ROUNDS):
            
            # The phone call to Claude with instructions, the transcript, 
            # the tool menu and existing personas
            response = self.llm.complete_with_tools(system, messages, TOOLS)
            
            # Claude's reply to the trascript
            messages.append({"role": "assistant", "content": response["content"]})

            
            # Claude didn't ask for a tool, so its done. Its text is the reply on screen,
            # e.g. "Done, I created Nurse Hugo." or a clarifying question like "what kind of person?"
            if response["stop_reason"] != "tool_use":
                reply = " ".join(b["text"] for b in response["content"] if b["type"] == "text").strip()
                reply = reply or "I didn't get a reply. Try rephrasing."

                # Remembers exchange by keeping most recent messages
                self.router_history += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
                self.router_history = self.router_history[-MAX_REMEMBERED_MESSAGES:]

                return Result(reply=reply, events=events, conversation=conversation)



            # Claude asked for tools. Collect a result for each tool.
            tool_results = []
            for block in response["content"]:
                if block["type"] != "tool_use":
                    continue

                # Run the method that matches the tool Claude asked for
                result = self._run_tool(block["name"], block["input"], on_turn=on_turn, on_start=on_start)
                
                
                events.extend(result.events)

                # When user ask for list of personas, they should see a list back
                if block["name"] == "list_personas":
                    events.append(result.reply)

                if result.conversation is not None:
                    conversation = result.conversation
                
                # Note for Claude with request's id
                tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": result.reply})

            # Add results to the transcript.
            messages.append({"role": "user", "content": tool_results})

        return Result(reply="I stopped after too many steps. Try a simpler request.", events=events, conversation=conversation)

    
    
    def _handle_regex(
        self,
        text: str,
        on_turn: Optional[Callable[[Turn], None]] = None,
        on_start: Optional[Callable[[str], None]] = None,
    ) -> Result:
        """
        The original regex router, kept as the offline fallback and a way to measure tool use against.

        Work out what the user meant and do it.

        Patterns are tried in order and the first match wins, so the ordering
        below is load-bearing — a fact that should make you suspicious of the
        whole approach.
        """
        lowered = text.strip().lower()

        # "create a persona doctor" / "make a persona who is a nurse"
        create = re.search(
            r"(?:create|make|add|build|generate)\s+(?:a\s+|an\s+|new\s+)*persona\s*(?:for|of|who is|that is|:)?\s*(.*)",
            lowered,
        )
        if create:
            return self._create_persona(create.group(1).strip())

        # "list personas" / "who do I have"
        if re.search(r"\b(list|show|what|who)\b.*\bpersona", lowered) or lowered in {"list", "ls"}:
            return self._list_personas()

        # "have them talk about X" / "start a conversation between A and B"
        converse = re.search(
            r"\b(?:talk|conversation|converse|chat|discuss|speak)\b",
            lowered,
        )
        if converse:
            topic_match = re.search(r"\babout\s+(.*)$", lowered)
            topic = topic_match.group(1).strip() if topic_match else "an initial consultation"

            who_match = re.search(r"\bbetween\s+(.*?)(?:\s+about\b|$)", lowered)
            who = None
            if who_match:
                who = [w.strip() for w in re.split(r"\s+and\s+|,", who_match.group(1)) if w.strip()]

            return self._converse(topic=topic, who=who, on_turn=on_turn, on_start=on_start)

        return self._chat(text)


# =============================================================================
# YOUR TASK
# =============================================================================
#
#  1. REPLACE THE REGEX ROUTER WITH REAL TOOL USE. This is the main event.
#     Claude supports tool calling: you describe the tools, the model picks one
#     and fills in the arguments. Roughly:
#
#         tools = [
#             {
#                 "name": "create_persona",
#                 "description": "Create and save a new persona character.",
#                 "input_schema": {
#                     "type": "object",
#                     "properties": {
#                         "description": {"type": "string",
#                                         "description": "What kind of person to create"},
#                     },
#                     "required": ["description"],
#                 },
#             },
#             {"name": "list_personas", ...},
#             {"name": "start_conversation", ...},   # participants, topic, turns
#         ]
#
#     Then loop: send the message with `tools=`, and while
#     `response.stop_reason == "tool_use"`, run the requested tool, append a
#     `tool_result` block, and send it back. The model handles "actually, make
#     it two doctors and a nurse, and have them argue about the diagnosis" —
#     which the regexes below will never manage.
#
#  2. The router cannot ask a clarifying question. "Create a persona" with no
#     description gets a canned string instead of "what kind of person?".
#
#  3. Pattern order decides meaning. "list the personas then have them talk"
#     only ever lists.
#
#  4. `_converse` silently picks the first two personas when you do not name
#     anyone, even if you have six.
#
#  5. `turns` is hardcoded to 6 and cannot be set from the conversation.
#
#  6. `self.history` grows without limit and is only used by `_chat`, so the
#     orchestrator has no memory of the personas it created.

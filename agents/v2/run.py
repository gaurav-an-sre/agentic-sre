"""CLI: python -m agents.v2.run investigate "<page text>" | approve P-xxxx | apply P-xxxx
Also: python -m agents.v1.run investigate ... (same runner, v1 agent)."""

from __future__ import annotations

import asyncio
import sys

from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.common.control_plane import approve


async def run_agent(agent, prompt: str) -> str:
    runner = InMemoryRunner(agent=agent, app_name="agentic-sre")
    session = await runner.session_service.create_session(app_name="agentic-sre", user_id="oncall")
    final = ""
    async for ev in runner.run_async(user_id="oncall", session_id=session.id,
                                     new_message=types.Content(role="user", parts=[types.Part(text=prompt)])):
        for part in (ev.content.parts if ev.content else []):
            if part.function_call:
                print(f"[{ev.author}] -> {part.function_call.name}({dict(part.function_call.args)})")
            elif part.function_response:
                print(f"[{ev.author}] <- {part.function_response.name}: "
                      f"{str(part.function_response.response)[:160]}")
            elif part.text and ev.is_final_response():
                final = part.text
                print(f"\n[{ev.author}]\n{part.text}\n")
    return final


def main(argv: list[str], version: str = "v2") -> None:
    cmd, arg = (argv + [""])[:2]
    if cmd == "approve":
        rec = approve(arg, approver="oncall-lead")
        print(f"approved {rec['id']} by {rec['approved_by']}")
        return
    if version == "v1":
        from agents.v1.agent import root_agent
        asyncio.run(run_agent(root_agent, arg))
        return
    from agents.v2.agent import applier, root_agent
    if cmd == "investigate":
        asyncio.run(run_agent(root_agent, arg))
    elif cmd == "apply":
        asyncio.run(run_agent(applier, f"Apply proposal {arg}."))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

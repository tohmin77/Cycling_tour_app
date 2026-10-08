import os

import anthropic

MODEL = "claude-sonnet-5-5"


def tool_json(system: str, user: str, name: str, schema: dict, max_tokens: int = 8000) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Import the itinerary as JSON instead (see samples/)."
        )
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        tools=[{"name": name, "description": "Record the structured result.", "input_schema": schema}],
        tool_choice={"type": "tool", "name": name},
        messages=[{"role": "user", "content": user}],
    )
    for block in msg.content:
        if block.type == "tool_use":
            return block.input
    raise ValueError("Model returned no structured result")

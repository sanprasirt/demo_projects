import json

from openai import OpenAI


class LLM:
    def __init__(self, base_url: str, model: str, api_key: str):
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def chat(self, *, phase: str, messages: list[dict], tools: list | None = None) -> dict:
        system = {
            "role": "system",
            "content": (
                f"PHASE={phase}\n"
                "You are a Day-2 SRE agent. Use only the provided tools. "
                "Cite evidence ids exactly as [e1]. Do not invent series or SHAs."
            ),
        }
        kwargs = {
            "model": self.model,
            "temperature": 0,
            "messages": [system, *messages],
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = self.client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            raw = call.function.arguments or "{}"
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError:
                arguments = {}
            calls.append({"id": call.id, "name": call.function.name, "arguments": arguments})
        return {"content": message.content or "", "tool_calls": calls}


def assistant_message(result: dict) -> dict:
    if not result["tool_calls"]:
        return {"role": "assistant", "content": result["content"]}
    return {
        "role": "assistant",
        "content": result["content"] or None,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["arguments"])},
            }
            for call in result["tool_calls"]
        ],
    }

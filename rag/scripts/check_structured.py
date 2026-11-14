import json
import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic()

schema = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "clause_id": {"type": "string"},
                },
                "required": ["doc_id", "clause_id"],
                "additionalProperties": False,
            },
        },
        "refused": {"type": "boolean"},
        "refusal_reason": {"type": "string"},
    },
    "required": ["answer", "citations", "refused", "refusal_reason"],
    "additionalProperties": False,
}

response = client.messages.create(
    model="claude-haiku-5-5",
    max_tokens=500,
    messages=[{
        "role": "user",
        "content": "Sources:\n[POL-01 4.2] Refunds are issued within 14 days.\n\nQuestion: How fast are refunds issued?",
    }],
    output_config={"format": {"type": "json_schema", "schema": schema}},
)
text = next(b.text for b in response.content if b.type == "text")
print(json.dumps(json.loads(text), indent=2))
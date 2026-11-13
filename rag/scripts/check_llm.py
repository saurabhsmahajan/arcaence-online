import os

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

if not os.environ.get("ANTHROPIC_API_KEY"):
    print("ANTHROPIC_API_KEY is missing from rag/.env")
    raise SystemExit(1)

client = Anthropic()
reply = client.messages.create(
    model="claude-haiku-5-5",
    max_tokens=20,
    messages=[{"role": "user", "content": "Reply with the single word: ready"}],
)
print(reply.content[0].text)
print("tokens in/out:", reply.usage.input_tokens, reply.usage.output_tokens)
"""Fixed settings for the policy server. There is no role to choose: this server has one job and one login."""

ROLE = "policy_reader"          # the database login this server must be connected as
TOOLS = frozenset({"search_policy"})

MAX_QUESTION = 500              # characters
MAX_K = 10                      # passages per call; the database function caps at 50 as well
DEFAULT_K = 5

# Must match the model the documents were embedded with (rag/ingest/embed.py). A different model would
# return confident nonsense, so the test suite compares the dimension and the startup check loads this exact name.
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIMENSIONS = 384

# Memory

Everything Eddy keeps between turns.

| Folder / file | What it holds |
|---|---|
| [`brain/`](brain/) | **Long-term memory**: a self-organizing network of notes (A-MEM) that decides what to remember, files it, links it, and rewrites old memories when facts change. Start here. |
| `conversation.py` | Chat sessions and message history (what the agent replays as working context) |
| `records/` | Structured records the agent manages with tools: goals, todos, settings, the approval queue |
| `storage/` | The backends: SQLite (schema + migrations for the whole app) and Qdrant (vectors) |

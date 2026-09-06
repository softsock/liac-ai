# Stack

| Area | Technology | Role |
| --- | --- | --- |
| Application and core runtime | Python with stdlib `sqlite3` | Runs Lilavel application behavior, the semantic conversational runtime, and Core-owned canonical/evidence persistence. The default store is in-memory; file-backed durability is explicit. |
| Model transport sidecar | TypeScript on Bun | Provides a small model-transport runtime where needed. |
| Provider layer | `@oh-my-pi/pi-ai@18.1.2` with `@oh-my-pi/pi-catalog@18.1.2` | Direct provider integration and bundled model selection for `openai-codex/gpt-5.6-luna`. |
| Discord text edge | Python with `discord.py==2.7.1` | Replaceable one-to-one DM transport and presentation adapter; depends on Core, never the reverse. |

Ownership boundaries and interaction invariants are defined in [ARCHITECTURE.md](ARCHITECTURE.md). Operational checks and result semantics are in [VALIDATION.md](VALIDATION.md), and architectural decisions are in [decisions/](decisions/).

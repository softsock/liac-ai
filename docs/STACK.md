# Stack

| Area | Technology | Role |
| --- | --- | --- |
| Application and core runtime | Python | Runs Lilavel application behavior and the semantic conversational runtime. |
| Model transport sidecar | TypeScript on Bun | Provides a small model-transport runtime where needed. |
| Provider layer | `@oh-my-pi/pi-ai` | Direct provider integration for `openai-codex/gpt-5.6-luna`. |

Ownership boundaries and interaction invariants are defined in [ARCHITECTURE.md](ARCHITECTURE.md).

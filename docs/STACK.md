# Stack

| Area | Technology | Role |
| --- | --- | --- |
| Application and core runtime | Python | Runs Lilavel application behavior and the semantic conversational runtime. |
| Model transport sidecar | TypeScript on Bun | Provides a small model-transport runtime where needed. |
| Provider layer | `@oh-my-pi/pi-ai@18.1.2` with `@oh-my-pi/pi-catalog@18.1.2` | Direct provider integration and bundled model selection for `openai-codex/gpt-5.6-luna`. |

Ownership boundaries and interaction invariants are defined in [ARCHITECTURE.md](ARCHITECTURE.md).

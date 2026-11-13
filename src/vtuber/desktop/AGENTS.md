# Desktop inspector

Optional PySide6 Widgets interface. Keep Qt imports inside this package. The
M4.4 source Lab reuses RuntimeWorker and LabHost; simulation has a new isolated
DB and independent OMP session. Manual input pauses it before submission.
Conversation/timeline retain bounded visible windows; old rows stay in archives.
Offline replay never starts providers. Keep historical context distinct from
current status and expose capture gaps. The bundled executable predates M4.4.

The
RuntimeWorker owns its asyncio loop, Journal, models and trace writer on one
thread. GUI commands marshal into that loop; signals contain copies or frozen
outputs. Never use a live Journal from the GUI thread, terminate a QThread, or
block GUI shutdown on model work. Close asynchronously and wait for owned work.

Trace detail loads off the GUI thread. Ignore stale selection generations.
Render untrusted text as plain text. Distinguish exact Fast wire prompts, OMP
session observations, missing history and partial output. Developer traces are
private and separate from domain events; never persist credentials/headers.

Run optional offscreen GUI checks via stdlib unittest; inspect a native window
and real providers separately. Fake results establish UI/lifecycle behavior only.

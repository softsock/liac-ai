"""Atomic human-readable projection; SQLite remains authoritative."""
import os
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile


def context_file_path(db: Path, character_id: str) -> Path:
    return db.parent / (db.name + '.contexts') / sha256(character_id.encode('utf-8')).hexdigest() / 'context.md'


def write_context(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text.encode('utf-8'))
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

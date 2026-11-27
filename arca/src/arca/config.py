"""Pfade und Schlüssel. Liest ``arca/.env`` (falls vorhanden) ohne zusätzliche Abhängigkeit."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ARCA_ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path = ARCA_ROOT / ".env") -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value.strip():
            os.environ.setdefault(key.strip(), value.strip())


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    data_dir: Path
    secret: bytes

    @property
    def vault_path(self) -> Path:
        return self.data_dir / "vault.db"

    @property
    def visible_path(self) -> Path:
        return self.data_dir / "visible.db"

    @classmethod
    def from_env(cls) -> "Config":
        load_env()
        secret = os.environ.get("ARCA_SECRET", "")
        if len(secret) < 32:
            raise ConfigError("ARCA_SECRET fehlt oder ist kürzer als 32 Zeichen (siehe arca/.env.example)")
        data_dir = Path(os.environ.get("ARCA_DATA_DIR") or ARCA_ROOT / "data")
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(data_dir=data_dir, secret=secret.encode())

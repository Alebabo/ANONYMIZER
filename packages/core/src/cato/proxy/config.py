"""Proxy configuration (``cato-proxy.yaml``).

Example::

    destination: external          # what sits behind the MCP client (default external)
    policy: support-default        # default policy for all upstreams
    upstreams:
      db:
        command: ["postgres-mcp", "--access-mode=restricted"]
        env: { DATABASE_URI: "${PROD_REPLICA_URI}" }
        mode: enforce              # enforce (default) | observe
        tools: { allow: ["execute_sql", "list_schemas"] }
      jira:
        url: https://jira-mcp.internal/mcp
        headers: { Authorization: "Bearer ${JIRA_TOKEN}" }

``${VAR}`` is replaced from the environment when the file is loaded, so secrets stay out of the file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

NAME = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
SEP = "__"

# Field names whose values are personal data regardless of what detection finds in the value.
# Normalized: lower case, without "_", "-", "." and spaces. Plain "name" is not included on purpose
# (table, tool and product names); add it per upstream with ``field_hints`` if it means a person there.
DEFAULT_FIELD_HINTS: dict[str, str] = {
    **dict.fromkeys(["firstname", "lastname", "surname", "fullname", "vorname", "nachname", "customername",
                     "kundenname", "contactname", "personname", "displayname", "username"], "person"),
    **dict.fromkeys(["email", "mail", "emailaddress", "emailadresse", "mailaddress"], "email"),
    **dict.fromkeys(["phone", "phonenumber", "telephone", "telefon", "telefonnummer", "mobile", "mobil",
                     "handy", "fax", "tel"], "phone"),
    **dict.fromkeys(["iban", "accountnumber", "kontonummer", "konto"], "iban"),
    **dict.fromkeys(["address", "adresse", "street", "strasse", "straße", "streetaddress", "anschrift",
                     "zip", "zipcode", "postcode", "postalcode", "plz"], "address"),
    **dict.fromkeys(["birthdate", "dateofbirth", "dob", "geburtsdatum", "birthday", "geburtstag"], "date_of_birth"),
    **dict.fromkeys(["taxid", "steuerid", "steueridentifikationsnummer"], "tax_id"),
    **dict.fromkeys(["ssn", "socialsecuritynumber",
                     "sozialversicherungsnummer", "svnr"], "social_security_number"),
    **dict.fromkeys(["ip", "ipaddress", "ipadresse"], "ip_address"),
}


def norm_key(key: str) -> str:
    return re.sub(r"[\s_\-.]", "", key).lower()


class ToolFilter(BaseModel):
    allow: list[str] | None = None  # exact tool names; None = all (minus deny and write tools)
    deny: list[str] = Field(default_factory=list)


class UpstreamConfig(BaseModel):
    command: list[str] | None = None
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    mode: Literal["enforce", "observe"] = "enforce"
    policy: str | None = None
    language: str | None = None
    tools: ToolFilter = Field(default_factory=ToolFilter)
    allow_write: bool = False  # expose tools annotated as not read-only / destructive
    field_hints: dict[str, str] = Field(default_factory=dict)  # field name -> entity type
    timeout: float = 60.0

    @model_validator(mode="after")
    def _one_transport(self) -> "UpstreamConfig":
        if bool(self.command) == bool(self.url):
            raise ValueError("set exactly one of 'command' (stdio) or 'url' (HTTP)")
        return self

    def hints(self) -> dict[str, str]:
        return DEFAULT_FIELD_HINTS | {norm_key(k): v for k, v in self.field_hints.items()}


class ProxyConfig(BaseModel):
    destination: Literal["external", "local"] = "external"
    policy: str = "support-default"
    custom_patterns: str | None = None
    max_chars: int = 500_000  # per tool result
    # stdio only (inside the API the API's stores are used). Point them at the API's files
    # (CATO_TRACE_DB / CATO_AUDIT_DB) to see proxy calls in the dashboard.
    trace_db: str | None = None
    audit_db: str | None = None
    org: str = "default"
    upstreams: dict[str, UpstreamConfig]

    @field_validator("upstreams")
    @classmethod
    def _names(cls, v: dict[str, UpstreamConfig]) -> dict[str, UpstreamConfig]:
        if not v:
            raise ValueError("at least one upstream is required")
        for name in v:
            if not NAME.match(name):
                raise ValueError(f"upstream name {name!r}: lower case letters, digits and '_', max. 24 characters")
        return v

    @classmethod
    def load(cls, path: str | Path, env: dict[str, str] | None = None) -> "ProxyConfig":
        env = dict(os.environ if env is None else env)
        raw = Path(path).read_text(encoding="utf-8")
        missing: list[str] = []

        def sub(m: re.Match) -> str:
            if m.group(1) not in env:
                missing.append(m.group(1))
                return ""
            return env[m.group(1)]

        text = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, raw)
        if missing:
            raise ValueError(f"environment variables not set: {', '.join(sorted(set(missing)))}")
        data = yaml.safe_load(text) or {}
        cfg = cls.model_validate(data)
        base = Path(path).resolve().parent
        for attr in ("custom_patterns", "trace_db", "audit_db"):
            value = getattr(cfg, attr)
            if value and not Path(value).is_absolute():
                setattr(cfg, attr, str(base / value))
        for up in cfg.upstreams.values():
            if up.cwd and not Path(up.cwd).is_absolute():
                up.cwd = str(base / up.cwd)
        return cfg

"""Versioned policy storage and scope resolution.

* Versions are immutable: saving an existing name requires ``version`` to
  be exactly latest + 1, and a stored version is never overwritten.
* Every stored version has a content hash; decisions reference
  ``name@vN`` and the hash, so audits can prove which rules applied.
* ``extends`` merges a parent policy: parent rules first, child rules after
  (child ids must be unique); scalar settings come from the child.
* Resolution for a request: team policy > tenant policy > global policy.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

from pydantic import BaseModel

from cato.policy.model import Policy, PolicyError


class PolicyVersion(BaseModel):
    name: str
    version: int
    hash: str
    scope: dict


class InMemoryPolicyStore:
    def __init__(self) -> None:
        self._versions: dict[str, dict[int, Policy]] = {}

    # -- write --------------------------------------------------------------
    def save(self, policy: Policy) -> Policy:
        versions = self._versions.get(policy.name, {})
        latest = max(versions) if versions else 0
        if policy.version != latest + 1:
            raise PolicyError(f"{policy.name}: expected version {latest + 1}, got {policy.version} "
                              "(versions are immutable)")
        if policy.extends:
            if policy.extends != policy.name:
                self.get(policy.extends)  # parent must exist
            # Reject now what would otherwise only fail when the policy is used
            # (id clash with the parent, circular chain): versions are immutable.
            self._resolve(policy, seen=set(), pending=policy)
        self._persist(policy)  # first: a failed write must not leave a phantom version
        self._versions.setdefault(policy.name, {})[policy.version] = policy
        return policy

    def _persist(self, policy: Policy) -> None:
        pass

    # -- read ---------------------------------------------------------------
    def get(self, name: str, version: int | None = None) -> Policy:
        versions = self._versions.get(name)
        if not versions:
            raise PolicyError(f"unknown policy {name}")
        v = version or max(versions)
        if v not in versions:
            raise PolicyError(f"unknown version {name}@v{v}")
        return versions[v]

    def history(self, name: str) -> list[PolicyVersion]:
        return [PolicyVersion(name=p.name, version=p.version, hash=p.content_hash, scope=p.scope.model_dump())
                for _, p in sorted(self._versions.get(name, {}).items())]

    def names(self) -> list[str]:
        return sorted(self._versions)

    def effective(self, name: str, version: int | None = None) -> Policy:
        """Policy with ``extends`` resolved."""
        return self._resolve(self.get(name, version), seen=set())

    def _resolve(self, policy: Policy, seen: set[str], pending: Policy | None = None) -> Policy:
        """``pending`` is a version about to be saved; it counts as the latest of its name."""
        if not policy.extends:
            return policy
        if policy.name in seen:
            raise PolicyError(f"circular extends at {policy.name}")
        parent = pending if pending is not None and policy.extends == pending.name else self.get(policy.extends)
        parent = self._resolve(parent, seen | {policy.name}, pending)
        parent_ids = {r.id for r in parent.rules} | {r.id for r in parent.document_rules}
        clash = parent_ids & ({r.id for r in policy.rules} | {r.id for r in policy.document_rules})
        if clash:
            raise PolicyError(f"{policy.name} reuses rule ids of {parent.name}: {sorted(clash)}")
        return policy.model_copy(update={
            "rules": [*parent.rules, *policy.rules],
            "document_rules": [*parent.document_rules, *policy.document_rules],
        })

    def resolve_for(self, tenant: str | None = None, team: str | None = None) -> Policy:
        """Most specific latest policy for a tenant/team."""
        latest = [self.get(n) for n in self.names()]

        def pick(pred) -> Policy | None:
            hits = [p for p in latest if pred(p.scope)]
            if len(hits) > 1:
                raise PolicyError(f"ambiguous policies for scope: {[p.name for p in hits]}")
            return hits[0] if hits else None

        candidates = []
        if tenant and team:
            candidates.append(lambda s: s.tenant == tenant and s.team == team)
        if tenant:
            candidates.append(lambda s: s.tenant == tenant and s.team is None)
        candidates.append(lambda s: s.tenant is None and s.team is None)
        for pred in candidates:
            if (p := pick(pred)) is not None:
                return self.effective(p.name)
        raise PolicyError("no policy applies (no global policy configured)")


class FilePolicyStore(InMemoryPolicyStore):
    """Stores each version as ``<dir>/<name>/v<N>.yaml`` (write-once)."""

    def __init__(self, directory: str | Path) -> None:
        super().__init__()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        for file in sorted(self.directory.glob("*/v*.yaml"), key=lambda f: (f.parent.name, _num(f))):
            policy = Policy.from_file(file)
            if policy.name != file.parent.name or policy.version != _num(file):
                raise PolicyError(f"{file}: name/version do not match the file location")
            self._versions.setdefault(policy.name, {})[policy.version] = policy

    def _persist(self, policy: Policy) -> None:
        path = self.directory / policy.name / f"v{policy.version}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "x", encoding="utf-8") as fh:  # 'x': never overwrite
                fh.write(policy.to_yaml())
        except FileExistsError:
            raise PolicyError(f"{policy.ref} already exists on disk (versions are immutable)") from None


def _num(path: Path) -> int:
    m = re.fullmatch(r"v(\d+)\.yaml", path.name)
    return int(m.group(1)) if m else 0


def builtin_policy(name: str = "legal-default") -> Policy:
    text = resources.files("cato.policy").joinpath(f"builtin/{name}.yaml").read_text(encoding="utf-8")
    return Policy.from_yaml(text)

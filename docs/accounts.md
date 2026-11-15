# Accounts, login and audit log

Cato has organizations, users with a simple e-mail/password login, organization-scoped API keys and an append-only audit log. Everything is stored in SQLite next to the traces (`/data` in Docker).

## Model

| Entity | Content | Scope |
|---|---|---|
| Organization | Name, trace retention | Owns all data below |
| User | E-mail, name, role `admin` or `member`, scrypt password hash | One organization |
| Session | SHA-256 of a random token, expiry (`CATO_SESSION_HOURS`, default 12) | One user |
| API key | Name, prefix, role `user` or `admin`, SHA-256 of the key, last use, revocation time | One organization |
| Audit entry | Actor, resource, action, before/after snapshot, hash chain | One organization |

Isolation:

- **Traces and metrics** carry the organization of the calling key or session. Every read is scoped to it.
- **Vault namespaces** are isolated per organization: the same namespace name in two organizations resolves to different vault entries. Namespaces containing control characters are rejected, so a prefix cannot be forged.
- **Policies are shared** by the installation. Only admins of the `default` organization may write them.
- **Environment keys** (`CATO_API_KEYS`, `CATO_ADMIN_KEYS`) belong to the `default` organization. They are still supported, and existing traces and vaults migrate to `default` without changes.

## Roles

| Action | admin (user) | member (user) | admin key | user key |
|---|---|---|---|---|
| Traces, metrics, policies, keys, members (read) | yes | yes | yes | yes |
| Create/revoke keys, manage members, organization settings | yes | – | yes | – |
| Read and verify the audit log | yes | – | yes | – |
| Write policies (default organization only) | yes | – | yes | – |
| `POST /v1/restore` | – | – | yes | – |

Restore needs an **admin API key**, never a dashboard session. Re-identification therefore always happens in a backend, and every restore is in the audit log.

## Getting started

```bash
# Docker: first admin via environment (only used while no user exists)
CATO_BOOTSTRAP_ADMIN_EMAIL=admin@kanzlei.example
CATO_BOOTSTRAP_ADMIN_PASSWORD=...   # min. 12 characters; change it after the first login

# or with the CLI (password is prompted)
docker compose exec api cato user create --email admin@kanzlei.example --role admin

# more organizations, users and demo traces
cato org create "Kanzlei B" --id kanzlei-b
cato user create --email b@kanzlei-b.example --org kanzlei-b
cato seed-demo --org kanzlei-b --count 400      # synthetic metadata-only traces
```

The dashboard needs `CATO_API_URL`. With it, every page requires a login; without it, the dashboard runs in demo mode with example data.

## Login security

- **Passwords:** scrypt (N=2^14, r=8, p=1) with a random salt. Minimum length 12.
- **Tokens and keys:** 256-bit random values, stored as SHA-256 only. A new API key is shown once.
- **Session cookie:** `httpOnly`, `SameSite=Lax`, `Secure` in production. The browser never sees the token in JavaScript. Server actions check the `Origin` header (CSRF).
- **Uniform failures:** an unknown e-mail and a wrong password give the same response. Unknown e-mails still run a dummy scrypt, so timing does not reveal accounts.
- **Rate limit:** 10 failed logins per e-mail within 15 minutes, then HTTP 429. The counter is in memory; with several API replicas, put a limiter in the reverse proxy as well.
- **Side effects:** a password change signs out the user's other sessions, and disabling a user ends all their sessions.
- **Admin safeguards:** you cannot remove your own admin access, and an organization always keeps at least one active admin.

## Audit log

The record shape follows Langfuse's audit log (`resourceType`, `resourceId`, `action`, `before`, `after`, actor = user / API key / system). The dashboard viewer under **Settings → Audit Logs** uses the same columns. It is Cato's own implementation: Langfuse's viewer is in its `ee/` directory and is not MIT-licensed.

| Resource | Actions |
|---|---|
| `session` | `login`, `login_failed` (actor `anonymous`), `logout` |
| `member` | `create`, `update` (role, disabled, name), `password_change` |
| `api_key` | `create`, `revoke` |
| `organization` | `create` (CLI), `update` |
| `policy` | `create`, `update` (version, hash, scope) |
| `vault` | `restore` (namespace, number of resolved placeholders) |
| `demo_data` | `seed` (CLI) |

Properties:

- **Append-only.** The store has no update or delete operation, and audit entries are not subject to trace retention.
- **Hash chain per organization:** `hash = sha256(prev_hash + entry)`. `GET /v1/audit-logs/verify` recomputes the chain and names the first broken entry; the dashboard shows the result. The chain detects edits and deletions inside the database. It does not stop someone who rewrites the whole file and the chain together. For that, export the chain head regularly (for example to WORM storage).
- **No secrets or content.** Snapshots pass a deny list (password hashes, key hashes, tokens, text, values). Restore events contain counts, never values.

## API

| Method | Path | Who | Function |
|---|---|---|---|
| POST | `/v1/auth/login` | – | E-mail + password → session token |
| POST | `/v1/auth/logout` | session | End the session |
| GET | `/v1/auth/me` | any | Caller, role, organization |
| POST | `/v1/auth/password` | session | Change the own password |
| GET / PATCH | `/v1/organization` | any / admin | Name, trace retention |
| GET / POST | `/v1/members` | any / admin | List, add |
| PATCH | `/v1/members/{id}` | admin | Role, disable, name |
| GET / POST | `/v1/api-keys` | any / admin | List, create (key returned once) |
| DELETE | `/v1/api-keys/{id}` | admin | Revoke |
| GET | `/v1/audit-logs` | admin | Filter `action`, `resource_type`, `actor_id`; page with `before` |
| GET | `/v1/audit-logs/{id}` | admin | One entry |
| GET | `/v1/audit-logs/verify` | admin | Check the hash chain |

## Limits

- **No SSO and no MFA yet.** Law firms will usually ask for both in procurement. Until then, put an identity-aware proxy in front for production.
- **No self-signup and no invitation e-mails.** Admins set an initial password and pass it on through a separate channel.
- **SQLite** is right for single-node self-hosting. A multi-node or SaaS deployment needs PostgreSQL behind the same interfaces.

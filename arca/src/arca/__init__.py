"""Arca: Originaldaten in vault.db (B), KI-sichtbare Kopie in visible.db (A).

Datenfluss: vault.db -> Cato (Erkennung) + Arca-Tokens -> Vorschau -> Freigabe -> visible.db -> MCP -> Claude.
Nichts aus diesem Paket wird vom MCP-Server importiert (siehe ``arca/mcp/server.py``).
"""

__version__ = "0.1.0"

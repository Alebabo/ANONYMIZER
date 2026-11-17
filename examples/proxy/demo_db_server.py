"""Demo upstream for the Anonymizer proxy: a fake customer database as an MCP server (stdio).

All data is synthetic. Use it to try the proxy before connecting a real system:

    anonymizer-proxy --config examples/proxy/anonymizer-proxy.yaml
"""

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

CUSTOMERS = [
    {"id": 1, "vorname": "Max", "nachname": "Mustermann", "email": "max.mustermann@example.org",
     "telefon": "+49 170 1234567", "iban": "DE89 3704 0044 0532 0130 00", "segment": "privat",
     "notiz": "Herr Mustermann hat am 12.03.2024 wegen der Kreditkarte angerufen."},
    {"id": 2, "vorname": "Erika", "nachname": "Musterfrau", "email": "erika@example.com",
     "telefon": "030 98765432", "iban": "DE02 1203 0000 0000 2020 51", "segment": "premium",
     "notiz": "Kundin ist wegen einer Depression krankgeschrieben, Rückruf erst nächste Woche."},
    {"id": 3, "vorname": "Jonas", "nachname": "Beispiel", "email": "j.beispiel@example.net",
     "telefon": "+49 151 22223333", "iban": "DE75 5121 0800 1245 1261 99", "segment": "privat",
     "notiz": "Adresse geändert auf Hauptstraße 5, 10115 Berlin."},
]
TICKETS = [
    {"ticket": "T-1001", "customer_id": 1, "status": "open",
     "text": "Hallo, mein Name ist Max Mustermann. Meine Karte wurde gesperrt, bitte um Rückruf unter 0170 1234567."},
    {"ticket": "T-1002", "customer_id": 3, "status": "closed",
     "text": "Überweisung an DE75 5121 0800 1245 1261 99 ist nicht angekommen. Gruß, Jonas Beispiel"},
]

server = MCPServer(name="demo-db", instructions="Synthetic customer database for testing the Anonymizer proxy.")


@server.tool(description="List tables and their columns.")
def list_tables() -> dict:
    return {"customers": list(CUSTOMERS[0]), "tickets": list(TICKETS[0])}


@server.tool(description="Return customers, optionally filtered by segment (privat, premium).")
def get_customers(segment: str | None = None, limit: int = 10) -> list[dict]:
    rows = [c for c in CUSTOMERS if segment is None or c["segment"] == segment]
    return rows[:limit]


@server.tool(description="Return support tickets with their free text.")
def get_tickets(status: str | None = None) -> list[dict]:
    return [t for t in TICKETS if status is None or t["status"] == status]


@server.tool(description="Plain-text export of one customer record.")
def export_customer(customer_id: int) -> str:
    c = next((c for c in CUSTOMERS if c["id"] == customer_id), None)
    if c is None:
        return "not found"
    return (f"Kunde {c['vorname']} {c['nachname']}, E-Mail {c['email']}, Telefon {c['telefon']}, "
            f"IBAN {c['iban']}. Notiz: {c['notiz']}")


@server.tool(description="Delete a customer (write tool, hidden by the proxy unless allow_write is set).",
             annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True))
def delete_customer(customer_id: int) -> str:
    return "deleted"


if __name__ == "__main__":
    server.run("stdio")

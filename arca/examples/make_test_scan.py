"""Erzeugt testscan_keller_nordbau.pdf: zweiseitiger, eingescannter Brief (nur Bild, keine Textebene).

Alle Namen, Firmen, Adressen, Nummern sind frei erfunden. Aufruf: python arca/examples/make_test_scan.py
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"

PAGES = [
    [
        ("b", "Dr. Hofmann & Partner Rechtsanwälte"),
        ("", "Am Wall 112 · 28195 Bremen · Tel. 0421 5566778"),
        ("", ""),
        ("", "Nordbau Projekt GmbH"),
        ("", "z. Hd. Herrn Geschäftsführer Uwe Brandt"),
        ("", "Hafenstraße 41"),
        ("", "28217 Bremen"),
        ("", ""),
        ("", "Bremen, 14.11.2026"),
        ("b", "Unser Zeichen: 12 U 45/23 – Keller Logistik AG ./. Nordbau Projekt GmbH"),
        ("", ""),
        ("", "Sehr geehrter Herr Brandt,"),
        ("", ""),
        ("", "wir vertreten die Keller Logistik AG, vertreten durch den Vorstand"),
        ("", "Frau Sabine Keller. Die Lagerhalle in der Überseestadt sollte"),
        ("", "vertragsgemäß am 31.03.2025 übergeben werden. Tatsächlich erfolgte"),
        ("", "die Abnahme erst am 19.09.2025. Ihr Bauleiter, Herr Jens Petersen,"),
        ("", "hat die Verzögerung in der Baubesprechung vom 02.04.2025 gegenüber"),
        ("", "unserer Mandantin eingeräumt. Zeugin hierfür ist Frau Dr. Miriam Ostrowski"),
        ("", "(Projektsteuerung, miriam.ostrowski@example-projekt.de)."),
    ],
    [
        ("", "Der Verzugsschaden beläuft sich nach dem Gutachten des Sachverständigen"),
        ("", "Dipl.-Ing. Klaus Vehrenkamp vom 08.10.2026 auf 1.250.000 Euro."),
        ("", "Wir fordern Sie auf, diesen Betrag bis zum 15.12.2026 auf das Konto"),
        ("", "unserer Mandantin zu überweisen:"),
        ("", ""),
        ("", "IBAN DE44 2905 0101 0012 3456 78, Sparkasse Bremen"),
        ("", ""),
        ("", "Die von Ihnen behauptete höhere Gewalt (Lieferengpass bei der"),
        ("", "Stahlbau Weser KG) entlastet Sie nicht; der Engpass war seit Januar"),
        ("", "2025 bekannt. Rückfragen richten Sie bitte an den Unterzeichner,"),
        ("", "Durchwahl 0421 5566779, oder an Frau Keller direkt unter"),
        ("", "0172 3344556."),
        ("", ""),
        ("", "Mit freundlichen Grüßen"),
        ("", ""),
        ("", "Dr. Thomas Hofmann"),
        ("", "Rechtsanwalt"),
    ],
]


def page(lines, seed: int) -> Image.Image:
    rng = random.Random(seed)
    w, h = 1654, 2339  # A4 bei 200 dpi
    img = Image.new("L", (w, h), 250)
    draw = ImageDraw.Draw(img)
    regular, bold = ImageFont.truetype(FONT, 30), ImageFont.truetype(BOLD, 30)
    y = 170
    for style, text in lines:
        draw.text((150, y), text, fill=25, font=bold if style == "b" else regular)
        y += 56
    # Scan-Eindruck: leichte Schräglage, Unschärfe, Rauschen
    img = img.rotate(rng.uniform(-0.6, 0.6), fillcolor=250, resample=Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    px = img.load()
    for _ in range(9000):
        x, yy = rng.randrange(w), rng.randrange(h)
        px[x, yy] = max(0, px[x, yy] - rng.randrange(40, 120))
    return img


if __name__ == "__main__":
    out = Path(__file__).with_name("testscan_keller_nordbau.pdf")
    images = [page(lines, i) for i, lines in enumerate(PAGES)]
    images[0].save(out, format="PDF", resolution=200.0, save_all=True, append_images=images[1:])
    print(out)

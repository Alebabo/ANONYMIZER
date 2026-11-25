"""Synthetic legal cases (run: python -I packages/core/scripts/newmean_legal_cases.py): newmean-pii (large) alone vs OpenAnonymizer (default) vs OpenAnonymizer + newmean."""
import time

from newmean_pii import create_redactor

from anonymizer.detect import Detector, DetectorConfig

CASES = {
    "Rubrum": "In dem Rechtsstreit\nder Frau Dr. Henrike Vollmer-Saß, Lindenallee 14, 50968 Köln,\n– Klägerin –\n"
              "Prozessbevollmächtigte: Rechtsanwälte Brandt & Kollegen, Hohenzollernring 22, 50672 Köln,\n"
              "gegen\ndie Nordwind Logistik GmbH, vertreten durch den Geschäftsführer Malte Oberhuber,\n– Beklagte –",
    "Aktenzeichen+Gericht": "Das Landgericht Köln, 3. Zivilkammer, hat durch den Vorsitzenden Richter am Landgericht "
                            "Dr. Kessler, die Richterin Yilmaz und den Richter Brandauer auf die mündliche Verhandlung "
                            "vom 12.03.2025 zum Aktenzeichen 3 O 214/24 für Recht erkannt:",
    "Normzitat": "Der Anspruch folgt aus § 280 Abs. 1 BGB i. V. m. § 241 Abs. 2 BGB; vgl. BGH, Urteil vom 14.05.2019 – "
                 "VI ZR 393/18, NJW 2019, 2539.",
    "Mandantenmail": "Sehr geehrter Herr Kowalczyk,\nanbei der Entwurf der Kündigungsschutzklage für Ihren Mandanten "
                     "Jens Petersen (geb. 03.07.1979, Steuer-ID 86 095 742 719). Bitte rufen Sie mich unter "
                     "0221 4478 120 an.\nMit freundlichen Grüßen\nRAin Sophie Lindqvist",
    "Handelsregister": "Die Beklagte ist im Handelsregister des Amtsgerichts Charlottenburg unter HRB 187654 B "
                       "eingetragen, USt-IdNr. DE 298 765 432, Geschäftsführerin ist Frau Aylin Demir.",
    "Zeuge+Gesundheit": "Der Zeuge Thomas Riedel bekundete, der Kläger leide seit dem Unfall an einer "
                        "posttraumatischen Belastungsstörung und sei bei Dr. med. Ursula Hahn in Behandlung.",
    "Bankverbindung": "Zahlung auf das Konto der Kanzlei, IBAN DE44 5001 0517 5407 3249 31, BIC INGDDEFFXXX, "
                      "Verwendungszweck: Mandat 2024/0815 Petersen ./. Nordwind.",
    "Kurzname im Text": "Petersen trug vor, Oberhuber habe ihm am Telefon die Kündigung angedroht. Nordwind bestreitet dies.",
}


def main() -> None:
    nm = create_redactor(size="large")
    base = Detector(DetectorConfig())
    both = Detector(DetectorConfig(newmean_model="large"))
    for name, text in CASES.items():
        print(f"\n=== {name} ===")
        t0 = time.perf_counter()
        spans = nm.detect(text)
        ms = (time.perf_counter() - t0) * 1000
        print(f"newmean large ({ms:.0f} ms):")
        for s in spans:
            print(f"   {s.label:14} {text[s.start:s.end]!r}")
        for label, det in (("OpenAnonymizer", base), ("OpenAnonymizer+newmean", both)):
            res = det.scan(text, "de")
            print(f"{label}:")
            for d in res.detections:
                print(f"   {d.entity_type:14} {d.text!r}  [{d.recognizer}]")


if __name__ == "__main__":
    main()

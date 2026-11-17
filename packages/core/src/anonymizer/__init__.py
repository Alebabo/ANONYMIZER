"""Anonymizer privacy engine."""

from anonymizer.detect import Detector, DetectorConfig
from anonymizer.models import Category, Detection, EntityType, ScanResult

__all__ = [
    "Category", "Detection", "Detector", "DetectorConfig", "EntityType", "ScanResult", "anonymize", "classify", "scan",
]
__version__ = "0.1.0"


_default: Detector | None = None


def scan(text: str, language: str | None = None) -> ScanResult:
    """Convenience wrapper using a shared detector with the default configuration."""
    global _default
    if _default is None:
        _default = Detector()
    return _default.scan(text, language)


def classify(text: str, language: str | None = None):
    """Detect and classify with default configuration."""
    from anonymizer.classify import Classifier

    return Classifier().classify_text(text, scan(text, language))


def anonymize(text: str, language: str | None = None, *, vault=None, namespace: str | None = None, config=None):
    """Detect and anonymize with default methods. Pass a vault and namespace
    for reversible pseudonyms."""
    from anonymizer.anonymize import Anonymizer

    return Anonymizer(config, vault=vault).anonymize(text, scan(text, language), namespace=namespace)

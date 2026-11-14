"""Cato privacy engine."""

from cato.detect import Detector, DetectorConfig
from cato.models import Category, Detection, EntityType, ScanResult

__all__ = ["Category", "Detection", "Detector", "DetectorConfig", "EntityType", "ScanResult", "scan"]
__version__ = "0.1.0"


_default: Detector | None = None


def scan(text: str, language: str | None = None) -> ScanResult:
    """Convenience wrapper using a shared detector with the default configuration."""
    global _default
    if _default is None:
        _default = Detector()
    return _default.scan(text, language)

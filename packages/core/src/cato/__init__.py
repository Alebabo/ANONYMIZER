"""Cato privacy engine."""

from cato.detect import Detector, DetectorConfig
from cato.models import Category, Detection, EntityType, ScanResult

__all__ = ["Category", "Detection", "Detector", "DetectorConfig", "EntityType", "ScanResult", "scan"]
__version__ = "0.1.0"


def scan(text: str, language: str | None = None) -> ScanResult:
    """Convenience wrapper using the default configuration."""
    return Detector().scan(text, language)

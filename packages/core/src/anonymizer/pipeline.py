"""End-to-end protection: detect -> classify -> policy -> anonymize.

This is the single entry point the gateway uses. The anonymized text is
only returned when the policy allows sending it to the requested
destination; otherwise ``text`` is ``None`` and the caller must not forward
anything.
"""

from __future__ import annotations

from pydantic import BaseModel

from anonymizer.anonymize import AnonymizationResult, OpenAnonymizer, AnonymizerConfig
from anonymizer.classify import Classifier, DocumentClassification
from anonymizer.detect import Detector
from anonymizer.policy import Policy, PolicyDecision, PolicyEngine, builtin_policy
from anonymizer.vault import Vault


class ProtectResult(BaseModel):
    text: str | None                          # safe to send; None if not allowed or dry run
    decision: PolicyDecision
    classification: DocumentClassification
    anonymization: AnonymizationResult | None

    @property
    def allowed(self) -> bool:
        return self.decision.may_send


class Pipeline:
    def __init__(
        self,
        policy: Policy | None = None,
        detector: Detector | None = None,
        classifier: Classifier | None = None,
        anonymizer_config: AnonymizerConfig | None = None,
        vault: Vault | None = None,
    ) -> None:
        self.policy = policy or builtin_policy()
        self.detector = detector or Detector()
        self.classifier = classifier or Classifier()
        self.anonymizer = OpenAnonymizer(anonymizer_config, vault=vault)

    def protect(
        self,
        text: str,
        destination: str = "external",
        namespace: str | None = None,
        language: str | None = None,
        dry_run: bool = False,
    ) -> ProtectResult:
        return self.protect_scan(text, self.detector.scan(text, language), destination, namespace, dry_run)

    def protect_scan(
        self,
        text: str,
        scan,
        destination: str = "external",
        namespace: str | None = None,
        dry_run: bool = False,
    ) -> ProtectResult:
        """Like :meth:`protect` with a precomputed (e.g. document-degraded) scan."""
        classification = self.classifier.classify_text(text, scan)
        decision = PolicyEngine(self.policy).evaluate(scan.detections, classification, destination, dry_run)
        anonymization = None
        # A dry run only reports the decision: no text, no vault entries.
        if decision.may_send and not dry_run:
            # Strict leak check raises before anything can be returned.
            anonymization = self.anonymizer.anonymize(text, scan, plan=decision.plan, namespace=namespace)
        return ProtectResult(
            text=anonymization.text if anonymization else None,
            decision=decision, classification=classification, anonymization=anonymization,
        )

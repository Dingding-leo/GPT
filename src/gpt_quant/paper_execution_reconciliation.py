from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .execution_quote_binding_journal import ExecutionQuoteBindingJournal
from .execution_quote_evidence import ExecutionQuoteEvidenceStore
from .paper_execution_attempt_journal import PaperExecutionAttemptJournal
from .target_intent_journal import TargetPositionIntentJournal

_SCHEMA_VERSION = 2
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EXCHANGE_FEE_ONE_WAY_BPS = "5"
_EXCHANGE_FEE_CONFIG_BYTES = b'{"component":"exchange_fee","one_way_bps":"5","version":1}\n'
_EXCHANGE_FEE_CONFIG_SHA256 = hashlib.sha256(_EXCHANGE_FEE_CONFIG_BYTES).hexdigest()
_FIELDS = {
    "schema_version",
    "intent_journal_sha256",
    "quote_store_sha256",
    "binding_journal_sha256",
    "attempt_journal_sha256",
    "intent_count",
    "quote_count",
    "binding_count",
    "attempt_count",
    "exchange_fee_one_way_bps",
    "exchange_fee_config_sha256",
    "spread_config_sha256",
    "slippage_config_sha256",
    "market_impact_config_sha256",
    "latency_config_sha256",
}
_SERIALIZED_FIELDS = _FIELDS | {"reconciliation_id"}


def _hash(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(
                f"paper execution reconciliation JSON contains duplicate field {key!r}"
            )
        result[key] = value
    return result


def _assert_root(label: str, expected: str, payload: bytes) -> None:
    observed = hashlib.sha256(payload).hexdigest()
    if observed != expected:
        raise ValueError(f"{label} SHA-256 does not match its canonical bytes")


def _verify_chain(
    *,
    intent_journal: TargetPositionIntentJournal,
    quote_store: ExecutionQuoteEvidenceStore,
    binding_journal: ExecutionQuoteBindingJournal,
    attempt_journal: PaperExecutionAttemptJournal,
) -> None:
    if not isinstance(intent_journal, TargetPositionIntentJournal):
        raise TypeError("intent_journal must be a TargetPositionIntentJournal")
    if not isinstance(quote_store, ExecutionQuoteEvidenceStore):
        raise TypeError("quote_store must be an ExecutionQuoteEvidenceStore")
    if not isinstance(binding_journal, ExecutionQuoteBindingJournal):
        raise TypeError("binding_journal must be an ExecutionQuoteBindingJournal")
    if not isinstance(attempt_journal, PaperExecutionAttemptJournal):
        raise TypeError("attempt_journal must be a PaperExecutionAttemptJournal")

    _assert_root("target intent journal", intent_journal.sha256, intent_journal.to_bytes())
    _assert_root("execution quote store", quote_store.sha256, quote_store.to_bytes())
    _assert_root(
        "execution quote binding journal",
        binding_journal.sha256,
        binding_journal.to_bytes(),
    )
    _assert_root(
        "paper execution attempt journal",
        attempt_journal.sha256,
        attempt_journal.to_bytes(),
    )

    intents = {intent.intent_id: intent for intent in intent_journal.intents}
    quotes = {quote.snapshot_id: quote for quote in quote_store.snapshots}
    bindings = {binding.binding_id: binding for binding in binding_journal.bindings}

    for binding in binding_journal.bindings:
        try:
            intent = intents[binding.target_intent_id]
        except KeyError as exc:
            raise ValueError(
                "execution quote binding journal references a missing target intent"
            ) from exc
        try:
            quote = quotes[binding.quote_snapshot_id]
        except KeyError as exc:
            raise ValueError(
                "execution quote binding journal references a missing execution quote"
            ) from exc
        binding.assert_reconstructs(intent, quote)

    for attempt in attempt_journal.attempts:
        try:
            binding = bindings[attempt.binding_id]
        except KeyError as exc:
            raise ValueError(
                "paper execution attempt journal references a missing execution binding"
            ) from exc
        try:
            quote = quotes[attempt.quote_snapshot_id]
        except KeyError as exc:
            raise ValueError(
                "paper execution attempt journal references a missing execution quote"
            ) from exc
        try:
            intent = intents[binding.target_intent_id]
        except KeyError as exc:
            raise ValueError(
                "paper execution attempt journal references a missing target intent"
            ) from exc
        attempt.assert_reconstructs(intent, binding, quote)


@dataclass(frozen=True, slots=True)
class PaperExecutionReconciliationEvidence:
    """Content-addressed root for one replayable paper-decision chain.

    The only modeled PnL cost is the canonical 5 bps one-way exchange-fee
    configuration. Spread, slippage, market impact, and latency remain independent
    observed-diagnostic configurations and are not added to paper PnL.
    """

    intent_journal_sha256: str
    quote_store_sha256: str
    binding_journal_sha256: str
    attempt_journal_sha256: str
    intent_count: int
    quote_count: int
    binding_count: int
    attempt_count: int
    exchange_fee_config_sha256: str
    spread_config_sha256: str
    slippage_config_sha256: str
    market_impact_config_sha256: str
    latency_config_sha256: str
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    exchange_fee_one_way_bps: str = field(default=_EXCHANGE_FEE_ONE_WAY_BPS, init=False)
    reconciliation_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "intent_journal_sha256",
            "quote_store_sha256",
            "binding_journal_sha256",
            "attempt_journal_sha256",
            "exchange_fee_config_sha256",
            "spread_config_sha256",
            "slippage_config_sha256",
            "market_impact_config_sha256",
            "latency_config_sha256",
        ):
            object.__setattr__(self, name, _hash(getattr(self, name), name))
        for name in ("intent_count", "quote_count", "binding_count", "attempt_count"):
            object.__setattr__(self, name, _count(getattr(self, name), name))
        if self.exchange_fee_config_sha256 != _EXCHANGE_FEE_CONFIG_SHA256:
            raise ValueError(
                "exchange_fee_config_sha256 must identify the canonical exact-5-bps-only config"
            )
        object.__setattr__(
            self,
            "reconciliation_id",
            hashlib.sha256(_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "intent_journal_sha256": self.intent_journal_sha256,
            "quote_store_sha256": self.quote_store_sha256,
            "binding_journal_sha256": self.binding_journal_sha256,
            "attempt_journal_sha256": self.attempt_journal_sha256,
            "intent_count": self.intent_count,
            "quote_count": self.quote_count,
            "binding_count": self.binding_count,
            "attempt_count": self.attempt_count,
            "exchange_fee_one_way_bps": self.exchange_fee_one_way_bps,
            "exchange_fee_config_sha256": self.exchange_fee_config_sha256,
            "spread_config_sha256": self.spread_config_sha256,
            "slippage_config_sha256": self.slippage_config_sha256,
            "market_impact_config_sha256": self.market_impact_config_sha256,
            "latency_config_sha256": self.latency_config_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "reconciliation_id": self.reconciliation_id}

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_dict()) + b"\n"

    def assert_reconstructs(
        self,
        *,
        intent_journal: TargetPositionIntentJournal,
        quote_store: ExecutionQuoteEvidenceStore,
        binding_journal: ExecutionQuoteBindingJournal,
        attempt_journal: PaperExecutionAttemptJournal,
        exchange_fee_config_sha256: str,
        spread_config_sha256: str,
        slippage_config_sha256: str,
        market_impact_config_sha256: str,
        latency_config_sha256: str,
    ) -> None:
        expected = reconcile_paper_execution_evidence(
            intent_journal=intent_journal,
            quote_store=quote_store,
            binding_journal=binding_journal,
            attempt_journal=attempt_journal,
            exchange_fee_config_sha256=exchange_fee_config_sha256,
            spread_config_sha256=spread_config_sha256,
            slippage_config_sha256=slippage_config_sha256,
            market_impact_config_sha256=market_impact_config_sha256,
            latency_config_sha256=latency_config_sha256,
        )
        if expected != self:
            raise ValueError("paper execution reconciliation does not match persisted evidence")

    @classmethod
    def from_mapping(cls, value: object) -> PaperExecutionReconciliationEvidence:
        if not isinstance(value, Mapping):
            raise ValueError("paper execution reconciliation must be a mapping")
        keys = set(value)
        if keys != _SERIALIZED_FIELDS:
            missing = sorted(_SERIALIZED_FIELDS - keys)
            unexpected = sorted(repr(key) for key in keys - _SERIALIZED_FIELDS)
            raise ValueError(
                "paper execution reconciliation fields do not match schema; "
                f"missing={missing}, unexpected={unexpected}"
            )
        schema_version = value["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != _SCHEMA_VERSION
        ):
            raise ValueError(
                f"unsupported paper execution reconciliation schema {schema_version!r}"
            )
        if value["exchange_fee_one_way_bps"] != _EXCHANGE_FEE_ONE_WAY_BPS:
            raise ValueError("paper execution reconciliation must declare the 5 bps one-way fee")
        evidence = cls(
            intent_journal_sha256=value["intent_journal_sha256"],
            quote_store_sha256=value["quote_store_sha256"],
            binding_journal_sha256=value["binding_journal_sha256"],
            attempt_journal_sha256=value["attempt_journal_sha256"],
            intent_count=value["intent_count"],
            quote_count=value["quote_count"],
            binding_count=value["binding_count"],
            attempt_count=value["attempt_count"],
            exchange_fee_config_sha256=value["exchange_fee_config_sha256"],
            spread_config_sha256=value["spread_config_sha256"],
            slippage_config_sha256=value["slippage_config_sha256"],
            market_impact_config_sha256=value["market_impact_config_sha256"],
            latency_config_sha256=value["latency_config_sha256"],
        )
        if value["reconciliation_id"] != evidence.reconciliation_id:
            raise ValueError("paper execution reconciliation ID does not match canonical payload")
        return evidence

    @classmethod
    def from_json_bytes(cls, value: bytes | str) -> PaperExecutionReconciliationEvidence:
        if isinstance(value, bytes):
            try:
                serialized = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("paper execution reconciliation JSON is unreadable") from exc
        elif isinstance(value, str):
            serialized = value
        else:
            raise ValueError("paper execution reconciliation JSON is unreadable")
        try:
            payload = json.loads(serialized, object_pairs_hook=_reject_duplicates)
        except (TypeError, ValueError) as exc:
            raise ValueError("paper execution reconciliation JSON is unreadable") from exc
        evidence = cls.from_mapping(payload)
        if evidence.to_json_bytes() != serialized.encode("utf-8"):
            raise ValueError("paper execution reconciliation JSON must use canonical encoding")
        return evidence


def reconcile_paper_execution_evidence(
    *,
    intent_journal: TargetPositionIntentJournal,
    quote_store: ExecutionQuoteEvidenceStore,
    binding_journal: ExecutionQuoteBindingJournal,
    attempt_journal: PaperExecutionAttemptJournal,
    exchange_fee_config_sha256: str,
    spread_config_sha256: str,
    slippage_config_sha256: str,
    market_impact_config_sha256: str,
    latency_config_sha256: str,
) -> PaperExecutionReconciliationEvidence:
    """Replay the chain and bind exact fee-only economics plus separate diagnostics."""

    _verify_chain(
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
        attempt_journal=attempt_journal,
    )
    return PaperExecutionReconciliationEvidence(
        intent_journal_sha256=intent_journal.sha256,
        quote_store_sha256=quote_store.sha256,
        binding_journal_sha256=binding_journal.sha256,
        attempt_journal_sha256=attempt_journal.sha256,
        intent_count=intent_journal.count,
        quote_count=quote_store.count,
        binding_count=binding_journal.count,
        attempt_count=attempt_journal.count,
        exchange_fee_config_sha256=exchange_fee_config_sha256,
        spread_config_sha256=spread_config_sha256,
        slippage_config_sha256=slippage_config_sha256,
        market_impact_config_sha256=market_impact_config_sha256,
        latency_config_sha256=latency_config_sha256,
    )

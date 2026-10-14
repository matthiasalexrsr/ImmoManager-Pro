"""In-memory collections of the dunning tables (mixed into storage.InMemoryStore).

Business rules live in services/dunning.py, which writes through document_versions.work()
(SQL session, or these collections with undo). Being dataclass fields of the store, the
collections are seen through the portfolio boundary (ScopedCollection) and are part of
snapshots like every other table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from .models_dunning import (
    DunningBaseRate,
    DunningBlock,
    DunningCase,
    DunningCaseItem,
    DunningDispute,
    DunningEvent,
    DunningLetter,
    DunningOutbox,
    DunningReply,
    DunningRun,
    DunningStageSetting,
)


@dataclass
class DunningMemoryStore:
    dunning_stage_settings: Dict[str, DunningStageSetting] = field(default_factory=dict)
    dunning_base_rates: Dict[str, DunningBaseRate] = field(default_factory=dict)
    dunning_blocks: Dict[str, DunningBlock] = field(default_factory=dict)
    dunning_disputes: Dict[str, DunningDispute] = field(default_factory=dict)
    dunning_runs: Dict[str, DunningRun] = field(default_factory=dict)
    dunning_cases: Dict[str, DunningCase] = field(default_factory=dict)
    dunning_case_items: Dict[str, DunningCaseItem] = field(default_factory=dict)
    dunning_letters: Dict[str, DunningLetter] = field(default_factory=dict)
    dunning_outbox: Dict[str, DunningOutbox] = field(default_factory=dict)
    dunning_replies: Dict[str, DunningReply] = field(default_factory=dict)
    dunning_events: Dict[str, DunningEvent] = field(default_factory=dict)

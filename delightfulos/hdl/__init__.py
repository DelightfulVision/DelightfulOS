"""HDL Layer — Wearable Hardware Description Language.

Five-dimensional grammar for describing and co-designing AI wearables:
  1. Body Location
  2. Signal Ecology
  3. Output Modality
  4. Intelligence Function
  5. Temporal Scope
"""

from delightfulos.hdl.grammar import (
    BodySite, SignalType, SignalDirection, OutputModality,
    IntelligenceClass, TemporalScope,
    Signal, Output, WearableSpec, WearableSystem,
)

__all__ = [
    "BodySite", "SignalType", "SignalDirection", "OutputModality",
    "IntelligenceClass", "TemporalScope",
    "Signal", "Output", "WearableSpec", "WearableSystem",
]

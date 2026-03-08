"""HDL Layer — Wearable Hardware Description Language.

Eight-dimensional grammar for describing and co-designing AI wearables
within an Internet of Bodies framework:
  1. Body Location       — anatomical site and affordances
  2. Signal Ecology      — sensing and emission modalities
  3. Output Modality     — how the device communicates back
  4. Intelligence Function — cognitive/somatic role
  5. Temporal Scope      — time horizon of operation
  6. Electronics         — components, power, connectivity
  7. Firmware            — embedded software architecture
  8. Interaction         — embodiment philosophy, consent, social dynamics

Device specs are YAML data files in hdl/library/devices/.
System specs are YAML data files in hdl/library/systems/.
Grammar types in grammar.py define the schema.
Loader in loader.py bridges data to types.
"""

from delightfulos.hdl.grammar import (
    BodySite, BodySiteProperties, SITE_PROPERTIES,
    SignalType, SignalDirection, Signal,
    OutputModality, Output,
    IntelligenceClass, TemporalScope,
    PowerSource, Connectivity, ElectronicsSpec,
    FirmwareFramework, DataProtocol, FirmwareSpec,
    ConsentModel, SocialDynamic, EmbodimentPrinciple, InteractionSpec,
    FormFactor,
    WearableSpec, WearableSystem,
)
from delightfulos.hdl.loader import library, parse_device, save_device

__all__ = [
    # Grammar types
    "BodySite", "BodySiteProperties", "SITE_PROPERTIES",
    "SignalType", "SignalDirection", "Signal",
    "OutputModality", "Output",
    "IntelligenceClass", "TemporalScope",
    "PowerSource", "Connectivity", "ElectronicsSpec",
    "FirmwareFramework", "DataProtocol", "FirmwareSpec",
    "ConsentModel", "SocialDynamic", "EmbodimentPrinciple", "InteractionSpec",
    "FormFactor",
    "WearableSpec", "WearableSystem",
    # Loader
    "library", "parse_device", "save_device",
]

"""HDL Library Loader — discovers and loads device/system specs from YAML data files.

The library directory structure:
    library/
        devices/          One YAML file per device spec
            collar_v1.yaml
            ...
        systems/          One YAML file per composed system (references devices by key)
            social_radar.yaml
            ...

Devices are data. Grammar is schema. This module is the bridge.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from delightfulos.hdl.grammar import (
    BodySite, Signal, SignalType, SignalDirection,
    Output, OutputModality,
    IntelligenceClass, TemporalScope,
    ElectronicsSpec, PowerSource, Connectivity,
    FirmwareSpec, FirmwareFramework, DataProtocol,
    InteractionSpec, ConsentModel, SocialDynamic, EmbodimentPrinciple,
    FormFactor,
    WearableSpec, WearableSystem,
)

log = logging.getLogger("delightfulos.hdl.loader")

LIBRARY_DIR = Path(__file__).parent / "library"
DEVICES_DIR = LIBRARY_DIR / "devices"
SYSTEMS_DIR = LIBRARY_DIR / "systems"


# ================================================================
# Parsing: YAML dict -> grammar types
# ================================================================

def _parse_signal(data: dict) -> Signal:
    return Signal(
        type=SignalType(data["type"]),
        direction=SignalDirection(data.get("direction", "sense")),
        sample_rate_hz=data.get("sample_rate_hz"),
        resolution_bits=data.get("resolution_bits"),
        range_min=data.get("range_min"),
        range_max=data.get("range_max"),
        power_mw=data.get("power_mw"),
        component=data.get("component", ""),
        notes=data.get("notes", ""),
    )


def _parse_output(data: dict) -> Output:
    return Output(
        modality=OutputModality(data["modality"]),
        directional=data.get("directional", False),
        channels=data.get("channels", 1),
        power_mw=data.get("power_mw"),
        component=data.get("component", ""),
        notes=data.get("notes", ""),
    )


def _safe_enum(enum_cls, value, fallback=None):
    """Parse an enum value, returning fallback if invalid."""
    try:
        return enum_cls(value)
    except (ValueError, KeyError):
        log.warning("Unknown %s value: %r", enum_cls.__name__, value)
        return fallback


def _safe_enum_list(enum_cls, values: list) -> list:
    """Parse a list of enum values, skipping invalids."""
    result = []
    for v in values or []:
        e = _safe_enum(enum_cls, v)
        if e is not None:
            result.append(e)
    return result


def _parse_electronics(data: dict | None) -> ElectronicsSpec:
    if not data:
        return ElectronicsSpec()
    return ElectronicsSpec(
        microcontroller=data.get("microcontroller", ""),
        mcu_cores=data.get("mcu_cores", 1),
        mcu_clock_mhz=data.get("mcu_clock_mhz", 0),
        mcu_flash_mb=data.get("mcu_flash_mb", 0),
        mcu_ram_kb=data.get("mcu_ram_kb", 0),
        connectivity=_safe_enum_list(Connectivity, data.get("connectivity", [])),
        power_source=_safe_enum(PowerSource, data.get("power_source"), PowerSource.LIPO),
        battery_mah=data.get("battery_mah", 0),
        estimated_runtime_hours=data.get("estimated_runtime_hours", 0),
        voltage=data.get("voltage", 3.3),
        total_power_mw=data.get("total_power_mw", 0),
        pcb_notes=data.get("pcb_notes", ""),
        bom_notes=data.get("bom_notes", ""),
    )


def _parse_firmware(data: dict | None) -> FirmwareSpec:
    if not data:
        return FirmwareSpec()
    return FirmwareSpec(
        framework=_safe_enum(FirmwareFramework, data.get("framework"), FirmwareFramework.ARDUINO),
        language=data.get("language", "C++"),
        data_protocol=_safe_enum(DataProtocol, data.get("data_protocol"), DataProtocol.WEBSOCKET_JSON),
        update_rate_hz=data.get("update_rate_hz", 5.0),
        edge_processing=data.get("edge_processing", []),
        server_processing=data.get("server_processing", []),
        power_modes=data.get("power_modes", []),
        ota_update=data.get("ota_update", False),
        notes=data.get("notes", ""),
    )


def _parse_interaction(data: dict | None) -> InteractionSpec:
    if not data:
        return InteractionSpec()
    return InteractionSpec(
        consent_model=_safe_enum(ConsentModel, data.get("consent_model"), ConsentModel.OPT_IN),
        social_dynamics=_safe_enum_list(SocialDynamic, data.get("social_dynamics", [])),
        embodiment_principles=_safe_enum_list(EmbodimentPrinciple, data.get("embodiment_principles", [])),
        social_signals=data.get("social_signals", []),
        signal_interpretations=data.get("signal_interpretations", {}),
        design_constraints=data.get("design_constraints", []),
        notes=data.get("notes", ""),
    )


def _parse_form_factor(data: dict | None) -> FormFactor:
    if not data:
        return FormFactor()
    return FormFactor(
        form=data.get("form", ""),
        weight_grams=data.get("weight_grams", 0),
        dimensions_mm=data.get("dimensions_mm", []),
        water_resistance=data.get("water_resistance", ""),
        materials=data.get("materials", []),
        notes=data.get("notes", ""),
    )


def parse_device(data: dict) -> WearableSpec:
    """Parse a dict (from YAML or JSON) into a WearableSpec."""
    return WearableSpec(
        name=data.get("name", "Unnamed"),
        body_site=BodySite(data["body_site"]),
        signals=[_parse_signal(s) for s in data.get("signals", [])],
        outputs=[_parse_output(o) for o in data.get("outputs", [])],
        intelligence=_safe_enum_list(IntelligenceClass, data.get("intelligence", [])),
        temporal=_safe_enum_list(TemporalScope, data.get("temporal", [])),
        electronics=_parse_electronics(data.get("electronics")),
        firmware=_parse_firmware(data.get("firmware")),
        interaction=_parse_interaction(data.get("interaction")),
        form_factor=_parse_form_factor(data.get("form_factor")),
        notes=data.get("notes", data.get("reasoning", "")),
    )


def parse_system(data: dict, device_registry: dict[str, WearableSpec]) -> WearableSystem:
    """Parse a system dict, resolving device references from the registry."""
    devices = []
    for ref in data.get("devices", []):
        if ref in device_registry:
            devices.append(device_registry[ref])
        else:
            log.warning("System '%s' references unknown device '%s'", data.get("name"), ref)

    return WearableSystem(
        name=data.get("name", "Unnamed"),
        description=data.get("description", ""),
        devices=devices,
        system_dynamics=_safe_enum_list(SocialDynamic, data.get("system_dynamics", [])),
        system_principles=_safe_enum_list(EmbodimentPrinciple, data.get("system_principles", [])),
    )


# ================================================================
# File I/O
# ================================================================

def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_device(key: str, spec: WearableSpec, directory: Path | None = None) -> Path:
    """Save a WearableSpec to a YAML file. Returns the path written."""
    directory = directory or DEVICES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(spec.to_dict(), f, default_flow_style=False, sort_keys=False,
                  width=120, allow_unicode=True)
    return path


def save_system(key: str, system: WearableSystem, device_keys: list[str],
                directory: Path | None = None) -> Path:
    """Save a WearableSystem to a YAML file. device_keys are the file keys for each device."""
    directory = directory or SYSTEMS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.yaml"
    data = {
        "name": system.name,
        "description": system.description,
        "devices": device_keys,
        "system_dynamics": [s.value for s in system.system_dynamics],
        "system_principles": [p.value for p in system.system_principles],
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False,
                  width=120, allow_unicode=True)
    return path


# ================================================================
# Library Registry
# ================================================================

class Library:
    """Registry of loaded device and system specs."""

    def __init__(self):
        self.devices: dict[str, WearableSpec] = {}
        self.systems: dict[str, WearableSystem] = {}
        self._loaded = False

    def load(self, devices_dir: Path | None = None, systems_dir: Path | None = None):
        """Load all YAML specs from the library directories."""
        devices_dir = devices_dir or DEVICES_DIR
        systems_dir = systems_dir or SYSTEMS_DIR

        self.devices.clear()
        self.systems.clear()

        # Load devices first (systems reference them)
        if devices_dir.is_dir():
            for path in sorted(devices_dir.glob("*.yaml")):
                key = path.stem
                try:
                    data = load_yaml(path)
                    self.devices[key] = parse_device(data)
                    log.debug("Loaded device: %s", key)
                except Exception as e:
                    log.error("Failed to load device %s: %s", path, e)

        # Load systems, resolving device references
        if systems_dir.is_dir():
            for path in sorted(systems_dir.glob("*.yaml")):
                key = path.stem
                try:
                    data = load_yaml(path)
                    self.systems[key] = parse_system(data, self.devices)
                    log.debug("Loaded system: %s", key)
                except Exception as e:
                    log.error("Failed to load system %s: %s", path, e)

        self._loaded = True
        log.info("HDL library loaded: %d devices, %d systems", len(self.devices), len(self.systems))

    def ensure_loaded(self):
        if not self._loaded:
            self.load()

    def add_device(self, key: str, spec: WearableSpec, persist: bool = False) -> str:
        """Add a device to the registry. Optionally save to disk."""
        self.devices[key] = spec
        if persist:
            save_device(key, spec)
        return key

    def add_system(self, key: str, system: WearableSystem, device_keys: list[str],
                   persist: bool = False) -> str:
        """Add a system to the registry. Optionally save to disk."""
        self.systems[key] = system
        if persist:
            save_system(key, system, device_keys)
        return key


# Singleton library instance
library = Library()

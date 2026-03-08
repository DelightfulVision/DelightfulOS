"""Wearable Hardware Description Language (HDL) — Compositional Grammar.

Defines the five-dimensional grammar for describing AI wearables:
  1. Body Location    — where on the body
  2. Signal Ecology   — what signals are sensed/emitted
  3. Output Modality  — how the system communicates back
  4. Intelligence Function — what cognitive role it serves
  5. Temporal Scope   — what timescale it operates on
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


# === Dimension 1: Body Location ===

class BodySite(str, Enum):
    HEAD = "head"
    EAR = "ear"
    NECK = "neck"
    CHEST = "chest"
    WRIST = "wrist"
    HAND = "hand"
    WAIST = "waist"
    FOOT = "foot"
    FULL_BODY = "full_body"


SITE_PROPERTIES = {
    BodySite.HEAD: {"proximity_to": ["eyes", "brain", "ears"], "motion_class": "orientation", "social_visibility": "high"},
    BodySite.EAR: {"proximity_to": ["ears", "brain"], "motion_class": "head_coupled", "social_visibility": "medium"},
    BodySite.NECK: {"proximity_to": ["throat", "jaw", "spine"], "motion_class": "head_coupled", "social_visibility": "medium"},
    BodySite.CHEST: {"proximity_to": ["heart", "lungs", "diaphragm"], "motion_class": "torso", "social_visibility": "low"},
    BodySite.WRIST: {"proximity_to": ["pulse", "hand"], "motion_class": "gesture", "social_visibility": "high"},
    BodySite.HAND: {"proximity_to": ["fingers", "palm"], "motion_class": "fine_motor", "social_visibility": "high"},
    BodySite.WAIST: {"proximity_to": ["core", "hip"], "motion_class": "gait", "social_visibility": "low"},
    BodySite.FOOT: {"proximity_to": ["ground", "ankle"], "motion_class": "gait", "social_visibility": "low"},
    BodySite.FULL_BODY: {"proximity_to": ["all"], "motion_class": "full", "social_visibility": "high"},
}


# === Dimension 2: Signal Ecology ===

class SignalType(str, Enum):
    VIBRATION = "vibration"
    PRESSURE = "pressure"
    STRAIN = "strain"
    EMG = "emg"
    EDA = "eda"
    ECG = "ecg"
    CAMERA = "camera"
    IR = "ir"
    PHOTOPLETHYSMOGRAPHY = "ppg"
    MICROPHONE = "microphone"
    ULTRASONIC = "ultrasonic"
    ACCELEROMETER = "accelerometer"
    GYROSCOPE = "gyroscope"
    MAGNETOMETER = "magnetometer"
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    GPS = "gps"
    DEPTH = "depth"
    CAPACITIVE = "capacitive"


class SignalDirection(str, Enum):
    SENSE = "sense"
    EMIT = "emit"
    BIDIRECTIONAL = "bidirectional"


@dataclass
class Signal:
    type: SignalType
    direction: SignalDirection = SignalDirection.SENSE
    sample_rate_hz: int | None = None
    resolution_bits: int | None = None
    notes: str = ""


# === Dimension 3: Output Modality ===

class OutputModality(str, Enum):
    HAPTIC_VIBRATION = "haptic_vibration"
    HAPTIC_PRESSURE = "haptic_pressure"
    HAPTIC_THERMAL = "haptic_thermal"
    VISUAL_LED = "visual_led"
    VISUAL_DISPLAY = "visual_display"
    VISUAL_AR = "visual_ar"
    AUDIO_SPEAKER = "audio_speaker"
    AUDIO_BONE_CONDUCTION = "audio_bone_conduction"
    NONE = "none"


@dataclass
class Output:
    modality: OutputModality
    directional: bool = False
    channels: int = 1
    notes: str = ""


# === Dimension 4: Intelligence Function ===

class IntelligenceClass(str, Enum):
    PERCEPTION = "perception"
    SOMATIC = "somatic"
    SOCIAL = "social"
    COGNITIVE = "cognitive"
    MOTOR = "motor"
    AFFECTIVE = "affective"
    COMMUNICATIVE = "communicative"


# === Dimension 5: Temporal Scope ===

class TemporalScope(str, Enum):
    ANTICIPATORY = "anticipatory"
    REACTIVE = "reactive"
    REFLECTIVE = "reflective"
    AMBIENT = "ambient"


# === Composed Wearable Specification ===

@dataclass
class WearableSpec:
    name: str
    body_site: BodySite
    signals: list[Signal] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=list)
    intelligence: list[IntelligenceClass] = field(default_factory=list)
    temporal: list[TemporalScope] = field(default_factory=list)
    microcontroller: str = ""
    connectivity: list[str] = field(default_factory=list)
    notes: str = ""

    def describe(self) -> str:
        lines = [
            f"=== {self.name} ===",
            f"Body Site: {self.body_site.value} ({SITE_PROPERTIES[self.body_site]['motion_class']})",
            f"Signals: {', '.join(s.type.value for s in self.signals)}",
            f"Outputs: {', '.join(o.modality.value for o in self.outputs)}",
            f"Intelligence: {', '.join(i.value for i in self.intelligence)}",
            f"Temporal: {', '.join(t.value for t in self.temporal)}",
            f"MCU: {self.microcontroller}",
            f"Connectivity: {', '.join(self.connectivity)}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "body_site": self.body_site.value,
            "signals": [{"type": s.type.value, "direction": s.direction.value, "sample_rate_hz": s.sample_rate_hz, "resolution_bits": s.resolution_bits} for s in self.signals],
            "outputs": [{"modality": o.modality.value, "directional": o.directional, "channels": o.channels} for o in self.outputs],
            "intelligence": [i.value for i in self.intelligence],
            "temporal": [t.value for t in self.temporal],
            "microcontroller": self.microcontroller,
            "connectivity": self.connectivity,
        }


# === Composition: Multi-device System ===

@dataclass
class WearableSystem:
    name: str
    devices: list[WearableSpec] = field(default_factory=list)

    def all_signals(self) -> list[Signal]:
        return [s for d in self.devices for s in d.signals]

    def all_outputs(self) -> list[Output]:
        return [o for d in self.devices for o in d.outputs]

    def all_intelligence(self) -> set[IntelligenceClass]:
        return {i for d in self.devices for i in d.intelligence}

    def coverage_report(self) -> str:
        sites = {d.body_site for d in self.devices}
        intel = self.all_intelligence()
        temporals = {t for d in self.devices for t in d.temporal}

        lines = [f"=== System: {self.name} ==="]
        lines.append(f"Devices: {len(self.devices)}")
        lines.append(f"Body sites covered: {', '.join(s.value for s in sites)}")
        lines.append(f"Intelligence classes: {', '.join(i.value for i in intel)}")
        lines.append(f"Temporal coverage: {', '.join(t.value for t in temporals)}")

        missing_sites = set(BodySite) - sites
        if missing_sites:
            lines.append(f"Uncovered sites: {', '.join(s.value for s in missing_sites)}")

        missing_intel = set(IntelligenceClass) - intel
        if missing_intel:
            lines.append(f"Uncovered intelligence: {', '.join(i.value for i in missing_intel)}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "devices": [d.to_dict() for d in self.devices],
        }

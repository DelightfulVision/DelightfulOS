"""Wearable Hardware Description Language (HDL) — Compositional Grammar.

A formal grammar for describing, composing, and reasoning about AI wearable
systems within an Internet of Bodies framework. Enables AI-assisted co-design
of full-stack wearable hardware: mechanical, electronic, firmware, interaction,
and philosophical dimensions.

Five primary dimensions:
  1. Body Location     — where on the body, anatomical affordances
  2. Signal Ecology    — what signals are sensed/emitted, at what fidelity
  3. Output Modality   — how the system communicates back to the wearer
  4. Intelligence Function — what cognitive/somatic role it serves
  5. Temporal Scope    — what timescale it operates on

Extended dimensions:
  6. Electronics       — components, power, connectivity
  7. Firmware          — embedded software architecture, protocols
  8. Interaction       — embodiment philosophy, consent, social dynamics
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ================================================================
# Dimension 1: Body Location
# ================================================================

class BodySite(str, Enum):
    HEAD = "head"
    EAR = "ear"
    NECK = "neck"
    CHEST = "chest"
    UPPER_ARM = "upper_arm"
    WRIST = "wrist"
    HAND = "hand"
    FINGER = "finger"
    WAIST = "waist"
    THIGH = "thigh"
    FOOT = "foot"
    FULL_BODY = "full_body"


@dataclass
class BodySiteProperties:
    """Anatomical and social properties of a body site."""
    proximity_to: list[str]
    motion_class: str           # orientation, head_coupled, torso, gesture, fine_motor, gait, full
    social_visibility: str      # high, medium, low
    skin_contact: bool          # whether the device typically contacts skin
    nerve_density: str          # high, medium, low (affects haptic resolution)
    anatomical_notes: str = ""


SITE_PROPERTIES: dict[BodySite, BodySiteProperties] = {
    BodySite.HEAD: BodySiteProperties(
        proximity_to=["eyes", "brain", "ears", "vestibular"],
        motion_class="orientation", social_visibility="high", skin_contact=False,
        nerve_density="high",
        anatomical_notes="Highest social visibility. Visual and auditory processing centers nearby.",
    ),
    BodySite.EAR: BodySiteProperties(
        proximity_to=["ears", "brain", "temporal_lobe"],
        motion_class="head_coupled", social_visibility="medium", skin_contact=True,
        nerve_density="medium",
        anatomical_notes="In-ear: body-conducted sound, PPG from ear canal. Around-ear: ambient audio.",
    ),
    BodySite.NECK: BodySiteProperties(
        proximity_to=["throat", "larynx", "jaw", "cervical_spine", "carotid", "vagus_nerve"],
        motion_class="head_coupled", social_visibility="medium", skin_contact=True,
        nerve_density="high",
        anatomical_notes="Unique access to speech production (larynx, vocal cords). "
        "Sub-vocalization detectable via contact mic. Vagus nerve proximity enables "
        "stress/arousal sensing. Social significance: necklaces, collars, ties — "
        "culturally loaded body site with connotations of trust and vulnerability.",
    ),
    BodySite.CHEST: BodySiteProperties(
        proximity_to=["heart", "lungs", "diaphragm", "sternum"],
        motion_class="torso", social_visibility="low", skin_contact=True,
        nerve_density="low",
        anatomical_notes="Cardiac and respiratory center. ECG, breathing rate, chest expansion.",
    ),
    BodySite.UPPER_ARM: BodySiteProperties(
        proximity_to=["bicep", "tricep", "shoulder"],
        motion_class="gesture", social_visibility="medium", skin_contact=True,
        nerve_density="medium",
        anatomical_notes="Arm gestures, muscle tension (EMG). Good for bands and patches.",
    ),
    BodySite.WRIST: BodySiteProperties(
        proximity_to=["pulse", "radial_artery", "hand"],
        motion_class="gesture", social_visibility="high", skin_contact=True,
        nerve_density="medium",
        anatomical_notes="Watch form factor. PPG for heart rate, accelerometer for activity. "
        "High social acceptance (watches are universal).",
    ),
    BodySite.HAND: BodySiteProperties(
        proximity_to=["fingers", "palm", "metacarpals"],
        motion_class="fine_motor", social_visibility="high", skin_contact=True,
        nerve_density="high",
        anatomical_notes="Highest dexterity. Gesture recognition, haptic feedback on palm/fingers.",
    ),
    BodySite.FINGER: BodySiteProperties(
        proximity_to=["fingertip", "nail_bed", "knuckle"],
        motion_class="fine_motor", social_visibility="high", skin_contact=True,
        nerve_density="high",
        anatomical_notes="Ring form factor. PPG, EDA, temperature. Extremely dense nerve endings.",
    ),
    BodySite.WAIST: BodySiteProperties(
        proximity_to=["core", "hip", "lumbar_spine"],
        motion_class="gait", social_visibility="low", skin_contact=False,
        nerve_density="low",
        anatomical_notes="Gait analysis, posture. Belt/clip form factor.",
    ),
    BodySite.THIGH: BodySiteProperties(
        proximity_to=["quadriceps", "femoral_artery"],
        motion_class="gait", social_visibility="low", skin_contact=True,
        nerve_density="low",
        anatomical_notes="Large muscle group for EMG. Patch or band form factor.",
    ),
    BodySite.FOOT: BodySiteProperties(
        proximity_to=["sole", "ankle", "achilles"],
        motion_class="gait", social_visibility="low", skin_contact=True,
        nerve_density="medium",
        anatomical_notes="Gait, balance, grounding. Insole or ankle band.",
    ),
    BodySite.FULL_BODY: BodySiteProperties(
        proximity_to=["all"],
        motion_class="full", social_visibility="high", skin_contact=True,
        nerve_density="medium",
        anatomical_notes="Garment-integrated. Distributed sensing across body surface.",
    ),
}


# ================================================================
# Dimension 2: Signal Ecology
# ================================================================

class SignalType(str, Enum):
    # Mechanical / vibration
    VIBRATION = "vibration"         # piezo contact mic, accelerometer-based
    PRESSURE = "pressure"           # force sensors, barometric
    STRAIN = "strain"               # stretch sensors, breathing bands
    # Bioelectric
    EMG = "emg"                     # electromyography (muscle)
    EDA = "eda"                     # electrodermal activity (galvanic skin response)
    ECG = "ecg"                     # electrocardiography (heart)
    EEG = "eeg"                     # electroencephalography (brain)
    EOG = "eog"                     # electrooculography (eye movement)
    # Optical
    CAMERA = "camera"               # RGB, stereo, wide-angle
    IR = "ir"                       # infrared imaging
    PHOTOPLETHYSMOGRAPHY = "ppg"    # blood volume pulse (optical heart rate)
    LIDAR = "lidar"                 # time-of-flight 3D scanning
    # Audio
    MICROPHONE = "microphone"       # air-conducted sound
    ULTRASONIC = "ultrasonic"       # distance, gesture
    BONE_CONDUCTION_MIC = "bone_conduction_mic"  # body-conducted sound
    # Inertial
    ACCELEROMETER = "accelerometer"
    GYROSCOPE = "gyroscope"
    MAGNETOMETER = "magnetometer"
    # Environmental
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    BAROMETRIC = "barometric"       # altitude, weather
    AIR_QUALITY = "air_quality"     # VOC, CO2, particulates
    AMBIENT_LIGHT = "ambient_light"
    UV = "uv"                       # UV exposure
    # Spatial
    GPS = "gps"
    UWB = "uwb"                     # ultra-wideband ranging
    DEPTH = "depth"                 # structured light / ToF depth camera
    RADAR = "radar"                 # mm-wave radar (gesture, vital signs)
    # Touch
    CAPACITIVE = "capacitive"       # intentional touch detection
    RESISTIVE = "resistive"         # pressure-sensitive touch


class SignalDirection(str, Enum):
    SENSE = "sense"
    EMIT = "emit"
    BIDIRECTIONAL = "bidirectional"


@dataclass
class Signal:
    """A single signal in the device's ecology."""
    type: SignalType
    direction: SignalDirection = SignalDirection.SENSE
    sample_rate_hz: int | None = None
    resolution_bits: int | None = None
    range_min: float | None = None
    range_max: float | None = None
    power_mw: float | None = None       # typical power consumption
    component: str = ""                  # specific part number or component name
    notes: str = ""

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "type": self.type.value,
            "direction": self.direction.value,
        }
        if self.sample_rate_hz is not None:
            d["sample_rate_hz"] = self.sample_rate_hz
        if self.resolution_bits is not None:
            d["resolution_bits"] = self.resolution_bits
        if self.range_min is not None:
            d["range_min"] = self.range_min
        if self.range_max is not None:
            d["range_max"] = self.range_max
        if self.power_mw is not None:
            d["power_mw"] = self.power_mw
        if self.component:
            d["component"] = self.component
        if self.notes:
            d["notes"] = self.notes
        return d


# ================================================================
# Dimension 3: Output Modality
# ================================================================

class OutputModality(str, Enum):
    # Haptic
    HAPTIC_VIBRATION = "haptic_vibration"       # ERM/LRA motors
    HAPTIC_PRESSURE = "haptic_pressure"         # pneumatic, mechanical
    HAPTIC_THERMAL = "haptic_thermal"           # peltier, resistive heating
    HAPTIC_ELECTROTACTILE = "haptic_electrotactile"  # electrical skin stimulation
    # Visual
    VISUAL_LED = "visual_led"
    VISUAL_DISPLAY = "visual_display"           # OLED, e-ink
    VISUAL_AR = "visual_ar"                     # waveguide, birdbath
    VISUAL_PROJECTION = "visual_projection"     # laser, DLP
    # Audio
    AUDIO_SPEAKER = "audio_speaker"
    AUDIO_BONE_CONDUCTION = "audio_bone_conduction"
    # Scent / chemical
    SCENT = "scent"                             # olfactory output
    # None
    NONE = "none"


@dataclass
class Output:
    """A single output channel."""
    modality: OutputModality
    directional: bool = False
    channels: int = 1
    power_mw: float | None = None
    component: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "modality": self.modality.value,
            "directional": self.directional,
            "channels": self.channels,
        }
        if self.power_mw is not None:
            d["power_mw"] = self.power_mw
        if self.component:
            d["component"] = self.component
        if self.notes:
            d["notes"] = self.notes
        return d


# ================================================================
# Dimension 4: Intelligence Function
# ================================================================

class IntelligenceClass(str, Enum):
    """What cognitive/somatic role the device serves in the IoB system."""
    PERCEPTION = "perception"           # what you see/hear (AR, spatial audio)
    SOMATIC = "somatic"                 # body state awareness (posture, breathing, tension)
    SOCIAL = "social"                   # interpersonal dynamics (turn-taking, proximity, attention)
    COGNITIVE = "cognitive"             # attention, memory, decision support
    MOTOR = "motor"                     # movement guidance, gesture recognition
    AFFECTIVE = "affective"             # emotional state, stress, arousal
    COMMUNICATIVE = "communicative"     # speech, expression, signaling to others
    PROPRIOCEPTIVE = "proprioceptive"   # body position in space, balance


# ================================================================
# Dimension 5: Temporal Scope
# ================================================================

class TemporalScope(str, Enum):
    ANTICIPATORY = "anticipatory"   # before events (pre-speech, pre-movement)
    REACTIVE = "reactive"           # during events (real-time response)
    REFLECTIVE = "reflective"       # after events (summaries, learning)
    AMBIENT = "ambient"             # continuous background (monitoring, context)
    EPISODIC = "episodic"           # discrete events (meetings, workouts, sessions)


# ================================================================
# Dimension 6: Electronics
# ================================================================

class PowerSource(str, Enum):
    LIPO = "lipo"
    COIN_CELL = "coin_cell"
    SUPERCAPACITOR = "supercapacitor"
    ENERGY_HARVEST = "energy_harvest"     # solar, kinetic, thermal
    USB_TETHERED = "usb_tethered"
    WIRELESS_CHARGING = "wireless_charging"


class Connectivity(str, Enum):
    WIFI = "wifi"
    BLE = "ble"
    BLE_MESH = "ble_mesh"
    UWB = "uwb"
    LORA = "lora"
    ZIGBEE = "zigbee"
    USB = "usb"
    I2S = "i2s"                           # inter-IC sound (audio bus)
    SPI = "spi"
    I2C = "i2c"
    UART = "uart"


@dataclass
class ElectronicsSpec:
    """Electronics design specification."""
    microcontroller: str = ""
    mcu_cores: int = 1
    mcu_clock_mhz: int = 0
    mcu_flash_mb: float = 0
    mcu_ram_kb: int = 0
    connectivity: list[Connectivity] = field(default_factory=list)
    power_source: PowerSource = PowerSource.LIPO
    battery_mah: int = 0
    estimated_runtime_hours: float = 0
    voltage: float = 3.3
    total_power_mw: float = 0
    pcb_notes: str = ""
    bom_notes: str = ""                    # bill of materials notes

    def to_dict(self) -> dict:
        return {
            "microcontroller": self.microcontroller,
            "mcu_cores": self.mcu_cores,
            "mcu_clock_mhz": self.mcu_clock_mhz,
            "mcu_flash_mb": self.mcu_flash_mb,
            "mcu_ram_kb": self.mcu_ram_kb,
            "connectivity": [c.value for c in self.connectivity],
            "power_source": self.power_source.value,
            "battery_mah": self.battery_mah,
            "estimated_runtime_hours": self.estimated_runtime_hours,
            "voltage": self.voltage,
            "total_power_mw": self.total_power_mw,
            "pcb_notes": self.pcb_notes,
            "bom_notes": self.bom_notes,
        }


# ================================================================
# Dimension 7: Firmware Architecture
# ================================================================

class FirmwareFramework(str, Enum):
    ARDUINO = "arduino"
    ESP_IDF = "esp_idf"
    ZEPHYR = "zephyr"
    MICROPYTHON = "micropython"
    CIRCUITPYTHON = "circuitpython"
    BARE_METAL = "bare_metal"
    RUST_EMBEDDED = "rust_embedded"


class DataProtocol(str, Enum):
    """How the device communicates with the server."""
    WEBSOCKET_JSON = "websocket_json"       # JSON events over WebSocket
    WEBSOCKET_BINARY = "websocket_binary"   # raw binary (audio, sensor streams)
    MQTT = "mqtt"
    BLE_GATT = "ble_gatt"
    HTTP_REST = "http_rest"
    OSC = "osc"                             # open sound control
    PROTOBUF = "protobuf"


@dataclass
class FirmwareSpec:
    """Firmware architecture specification."""
    framework: FirmwareFramework = FirmwareFramework.ARDUINO
    language: str = "C++"
    data_protocol: DataProtocol = DataProtocol.WEBSOCKET_JSON
    update_rate_hz: float = 5.0             # how often it sends data to server
    edge_processing: list[str] = field(default_factory=list)  # what runs on-device
    server_processing: list[str] = field(default_factory=list)  # what runs on server
    power_modes: list[str] = field(default_factory=list)  # sleep, low-power, active
    ota_update: bool = False
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "framework": self.framework.value,
            "language": self.language,
            "data_protocol": self.data_protocol.value,
            "update_rate_hz": self.update_rate_hz,
            "edge_processing": self.edge_processing,
            "server_processing": self.server_processing,
            "power_modes": self.power_modes,
            "ota_update": self.ota_update,
            "notes": self.notes,
        }


# ================================================================
# Dimension 8: Interaction & Embodiment
# ================================================================

class ConsentModel(str, Enum):
    """How the device handles consent for data and interaction."""
    OPT_IN = "opt_in"                       # explicit activation required
    AMBIENT_REVOCABLE = "ambient_revocable"  # always on, can be turned off
    MUTUAL = "mutual"                        # requires consent from both parties
    CONTEXTUAL = "contextual"                # adjusts based on social context


class SocialDynamic(str, Enum):
    """What social relationship the device mediates."""
    SELF = "self"                            # self-awareness, personal state
    DYADIC = "dyadic"                        # two-person interaction
    GROUP = "group"                          # multi-person dynamics
    ENVIRONMENTAL = "environmental"          # person-environment relationship
    ASYMMETRIC = "asymmetric"                # observer/observed roles differ


class EmbodimentPrinciple(str, Enum):
    """Philosophical/psychological framework informing the design."""
    PROPRIOCEPTION = "proprioception"        # awareness of body in space
    INTEROCEPTION = "interoception"          # awareness of internal body state
    EXTEROCEPTION = "exteroception"          # awareness of external environment
    SHARED_PERCEPTION = "shared_perception"  # experiencing another's sensorium
    CONSENT_PLAY = "consent_play"            # touch as negotiated interaction
    AMBIENT_INTELLIGENCE = "ambient_intelligence"  # technology that disappears
    EXTENDED_MIND = "extended_mind"          # cognition distributed across body+tech
    SOMATIC_MARKERS = "somatic_markers"      # body signals as decision heuristics (Damasio)
    UMWELT = "umwelt"                        # each organism's subjective perceptual world (von Uexkull)
    AFFORDANCE = "affordance"                # what the body-tech system invites (Gibson)


@dataclass
class InteractionSpec:
    """Interaction design and embodiment philosophy specification."""
    consent_model: ConsentModel = ConsentModel.OPT_IN
    social_dynamics: list[SocialDynamic] = field(default_factory=list)
    embodiment_principles: list[EmbodimentPrinciple] = field(default_factory=list)
    # What the device detects about social state
    social_signals: list[str] = field(default_factory=list)
    # What body signals mean psychologically
    signal_interpretations: dict[str, str] = field(default_factory=dict)
    # Design constraints from embodiment philosophy
    design_constraints: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "consent_model": self.consent_model.value,
            "social_dynamics": [s.value for s in self.social_dynamics],
            "embodiment_principles": [e.value for e in self.embodiment_principles],
            "social_signals": self.social_signals,
            "signal_interpretations": self.signal_interpretations,
            "design_constraints": self.design_constraints,
            "notes": self.notes,
        }


# ================================================================
# Composed Wearable Specification
# ================================================================

@dataclass
class FormFactor:
    """Physical form of the device."""
    form: str = ""                          # band, clip, ring, patch, garment, pendant, glasses
    weight_grams: float = 0
    dimensions_mm: list[float] = field(default_factory=list)  # [length, width, height]
    water_resistance: str = ""              # IPX rating
    materials: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"form": self.form}
        if self.weight_grams:
            d["weight_grams"] = self.weight_grams
        if self.dimensions_mm:
            d["dimensions_mm"] = self.dimensions_mm
        if self.water_resistance:
            d["water_resistance"] = self.water_resistance
        if self.materials:
            d["materials"] = self.materials
        if self.notes:
            d["notes"] = self.notes
        return d


@dataclass
class WearableSpec:
    """Complete wearable device specification across all dimensions."""
    name: str
    body_site: BodySite

    # Dimension 2: Signal Ecology
    signals: list[Signal] = field(default_factory=list)
    # Dimension 3: Output Modality
    outputs: list[Output] = field(default_factory=list)
    # Dimension 4: Intelligence Function
    intelligence: list[IntelligenceClass] = field(default_factory=list)
    # Dimension 5: Temporal Scope
    temporal: list[TemporalScope] = field(default_factory=list)
    # Dimension 6: Electronics
    electronics: ElectronicsSpec = field(default_factory=ElectronicsSpec)
    # Dimension 7: Firmware
    firmware: FirmwareSpec = field(default_factory=FirmwareSpec)
    # Dimension 8: Interaction & Embodiment
    interaction: InteractionSpec = field(default_factory=InteractionSpec)
    # Physical form
    form_factor: FormFactor = field(default_factory=FormFactor)

    # Legacy fields (for backward compat with existing specs)
    microcontroller: str = ""
    connectivity: list[str] = field(default_factory=list)
    notes: str = ""

    def describe(self) -> str:
        props = SITE_PROPERTIES.get(self.body_site)
        lines = [
            f"=== {self.name} ===",
            f"Body Site: {self.body_site.value}",
        ]
        if props:
            lines.append(f"  Motion class: {props.motion_class}")
            lines.append(f"  Social visibility: {props.social_visibility}")
            lines.append(f"  Anatomical: {props.anatomical_notes}")

        lines.append(f"Signals: {', '.join(s.type.value for s in self.signals)}")
        lines.append(f"Outputs: {', '.join(o.modality.value for o in self.outputs)}")
        lines.append(f"Intelligence: {', '.join(i.value for i in self.intelligence)}")
        lines.append(f"Temporal: {', '.join(t.value for t in self.temporal)}")

        mcu = self.electronics.microcontroller or self.microcontroller
        if mcu:
            lines.append(f"MCU: {mcu}")
        conn = self.electronics.connectivity or [Connectivity(c) for c in self.connectivity if c in Connectivity.__members__.values()]
        if conn:
            lines.append(f"Connectivity: {', '.join(c.value if isinstance(c, Connectivity) else c for c in conn)}")
        if self.form_factor.form:
            lines.append(f"Form: {self.form_factor.form}")
        if self.interaction.embodiment_principles:
            lines.append(f"Embodiment: {', '.join(e.value for e in self.interaction.embodiment_principles)}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "body_site": self.body_site.value,
            "signals": [s.to_dict() for s in self.signals],
            "outputs": [o.to_dict() for o in self.outputs],
            "intelligence": [i.value for i in self.intelligence],
            "temporal": [t.value for t in self.temporal],
            "electronics": self.electronics.to_dict(),
            "firmware": self.firmware.to_dict(),
            "interaction": self.interaction.to_dict(),
            "form_factor": self.form_factor.to_dict(),
            "notes": self.notes,
        }


# ================================================================
# Composition: Multi-device System
# ================================================================

@dataclass
class WearableSystem:
    """A composed system of multiple wearable devices."""
    name: str
    devices: list[WearableSpec] = field(default_factory=list)
    description: str = ""
    # System-level interaction
    system_dynamics: list[SocialDynamic] = field(default_factory=list)
    system_principles: list[EmbodimentPrinciple] = field(default_factory=list)

    def all_signals(self) -> list[Signal]:
        return [s for d in self.devices for s in d.signals]

    def all_outputs(self) -> list[Output]:
        return [o for d in self.devices for o in d.outputs]

    def all_intelligence(self) -> set[IntelligenceClass]:
        return {i for d in self.devices for i in d.intelligence}

    def body_coverage(self) -> set[BodySite]:
        return {d.body_site for d in self.devices}

    def coverage_report(self) -> str:
        sites = self.body_coverage()
        intel = self.all_intelligence()
        temporals = {t for d in self.devices for t in d.temporal}
        signals = {s.type for s in self.all_signals()}
        outputs = {o.modality for o in self.all_outputs()}

        lines = [f"=== System: {self.name} ==="]
        if self.description:
            lines.append(self.description)
        lines.append(f"Devices: {len(self.devices)}")
        lines.append(f"Body sites: {', '.join(s.value for s in sites)}")
        lines.append(f"Signal types: {', '.join(s.value for s in signals)}")
        lines.append(f"Output modalities: {', '.join(o.value for o in outputs)}")
        lines.append(f"Intelligence classes: {', '.join(i.value for i in intel)}")
        lines.append(f"Temporal coverage: {', '.join(t.value for t in temporals)}")

        # Gap analysis
        missing_sites = set(BodySite) - sites
        if missing_sites:
            lines.append(f"Uncovered body sites: {', '.join(s.value for s in missing_sites)}")

        missing_intel = set(IntelligenceClass) - intel
        if missing_intel:
            lines.append(f"Uncovered intelligence: {', '.join(i.value for i in missing_intel)}")

        missing_temporal = set(TemporalScope) - temporals
        if missing_temporal:
            lines.append(f"Uncovered temporal: {', '.join(t.value for t in missing_temporal)}")

        # Interaction analysis
        if self.system_dynamics:
            lines.append(f"Social dynamics: {', '.join(d.value for d in self.system_dynamics)}")
        if self.system_principles:
            lines.append(f"Embodiment: {', '.join(p.value for p in self.system_principles)}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "devices": [d.to_dict() for d in self.devices],
            "system_dynamics": [s.value for s in self.system_dynamics],
            "system_principles": [p.value for p in self.system_principles],
        }

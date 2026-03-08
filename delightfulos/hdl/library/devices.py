"""Pre-built device specifications from the HDL grammar."""
from delightfulos.hdl.grammar import (
    BodySite, Signal, SignalType, SignalDirection,
    Output, OutputModality,
    IntelligenceClass, TemporalScope,
    WearableSpec, WearableSystem,
)


COLLAR_V1 = WearableSpec(
    name="DelightfulOS Collar v1",
    body_site=BodySite.NECK,
    signals=[
        Signal(SignalType.VIBRATION, SignalDirection.SENSE, sample_rate_hz=4000, resolution_bits=12,
               notes="Piezo contact mic on throat — pre-speech, speech, swallowing"),
        Signal(SignalType.MICROPHONE, SignalDirection.SENSE, sample_rate_hz=16000, resolution_bits=16,
               notes="MEMS air mic for actual speech capture/transcription"),
        Signal(SignalType.DEPTH, SignalDirection.SENSE,
               notes="3D depth camera — scene understanding, gesture, proximity"),
    ],
    outputs=[
        Output(OutputModality.HAPTIC_VIBRATION, directional=True, channels=4,
               notes="Front/left/right/back vibration motors for directional cues"),
    ],
    intelligence=[
        IntelligenceClass.SOCIAL,
        IntelligenceClass.SOMATIC,
        IntelligenceClass.COMMUNICATIVE,
        IntelligenceClass.AFFECTIVE,
    ],
    temporal=[
        TemporalScope.ANTICIPATORY,
        TemporalScope.REACTIVE,
        TemporalScope.AMBIENT,
    ],
    microcontroller="XIAO ESP32-S3 Sense",
    connectivity=["wifi", "ble"],
    notes="Near-egocentric wearable for social AR mediation",
)


SPECTACLES = WearableSpec(
    name="Snap Spectacles (5th Gen)",
    body_site=BodySite.HEAD,
    signals=[
        Signal(SignalType.CAMERA, SignalDirection.SENSE, notes="Stereo RGB cameras"),
        Signal(SignalType.DEPTH, SignalDirection.SENSE, notes="Spatial mapping / mesh"),
        Signal(SignalType.MICROPHONE, SignalDirection.SENSE, notes="Built-in mics"),
        Signal(SignalType.ACCELEROMETER, SignalDirection.SENSE),
        Signal(SignalType.GYROSCOPE, SignalDirection.SENSE),
    ],
    outputs=[
        Output(OutputModality.VISUAL_AR, directional=False, channels=2,
               notes="Dual waveguide AR display"),
        Output(OutputModality.AUDIO_SPEAKER, directional=False, channels=2),
    ],
    intelligence=[
        IntelligenceClass.PERCEPTION,
        IntelligenceClass.SOCIAL,
        IntelligenceClass.COGNITIVE,
    ],
    temporal=[
        TemporalScope.REACTIVE,
        TemporalScope.AMBIENT,
    ],
    microcontroller="Qualcomm AR1 Gen 1",
    connectivity=["ble", "wifi"],
    notes="AR glasses — perception layer",
)


CHEST_BAND = WearableSpec(
    name="Respiration Band",
    body_site=BodySite.CHEST,
    signals=[
        Signal(SignalType.STRAIN, SignalDirection.SENSE, sample_rate_hz=100,
               notes="Stretch sensor for breathing rate/depth"),
        Signal(SignalType.ECG, SignalDirection.SENSE, sample_rate_hz=250,
               notes="Single-lead ECG for heart rate/HRV"),
    ],
    outputs=[
        Output(OutputModality.HAPTIC_VIBRATION, directional=False, channels=1,
               notes="Breathing pace guide"),
    ],
    intelligence=[
        IntelligenceClass.SOMATIC,
        IntelligenceClass.AFFECTIVE,
    ],
    temporal=[
        TemporalScope.AMBIENT,
        TemporalScope.REFLECTIVE,
    ],
    microcontroller="XIAO ESP32-S3",
    connectivity=["ble"],
)


EARABLE = WearableSpec(
    name="Attention Earable",
    body_site=BodySite.EAR,
    signals=[
        Signal(SignalType.MICROPHONE, SignalDirection.SENSE, sample_rate_hz=16000),
        Signal(SignalType.ACCELEROMETER, SignalDirection.SENSE),
        Signal(SignalType.PHOTOPLETHYSMOGRAPHY, SignalDirection.SENSE, notes="In-ear PPG for HR"),
    ],
    outputs=[
        Output(OutputModality.AUDIO_BONE_CONDUCTION, directional=False, channels=2),
    ],
    intelligence=[
        IntelligenceClass.PERCEPTION,
        IntelligenceClass.COGNITIVE,
    ],
    temporal=[
        TemporalScope.REACTIVE,
        TemporalScope.AMBIENT,
    ],
    microcontroller="XIAO RP2040",
    connectivity=["ble"],
)


# === Composed Systems ===

SOCIAL_RADAR = WearableSystem(
    name="Social Radar",
    devices=[COLLAR_V1, SPECTACLES],
)

FULL_BODY_STACK = WearableSystem(
    name="Full IoB Stack",
    devices=[COLLAR_V1, SPECTACLES, CHEST_BAND, EARABLE],
)

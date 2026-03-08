"""AI-assisted hardware co-design using the HDL grammar."""
import json
from delightfulos.hdl.grammar import (
    BodySite, SignalType, SignalDirection, OutputModality,
    IntelligenceClass, TemporalScope,
    Signal, Output, WearableSpec, WearableSystem,
)

CODESIGN_SYSTEM_PROMPT = """You are a wearable hardware co-design assistant. You help design AI wearable devices using a structured grammar.

The grammar has five dimensions:

1. BODY SITE: head, ear, neck, chest, wrist, hand, waist, foot, full_body

2. SIGNAL TYPES (sensors):
   vibration, pressure, strain, emg, eda, ecg, camera, ir, ppg,
   microphone, ultrasonic, accelerometer, gyroscope, magnetometer,
   temperature, humidity, gps, depth, capacitive
   Each signal has: direction (sense/emit/bidirectional), sample_rate_hz, resolution_bits

3. OUTPUT MODALITIES:
   haptic_vibration, haptic_pressure, haptic_thermal, visual_led,
   visual_display, visual_ar, audio_speaker, audio_bone_conduction, none
   Each output has: directional (bool), channels (int)

4. INTELLIGENCE CLASSES:
   perception, somatic, social, cognitive, motor, affective, communicative

5. TEMPORAL SCOPES:
   anticipatory (before events), reactive (during), reflective (after), ambient (continuous)

When the user describes what they want, respond with ONLY a JSON object:
{
  "name": "device name",
  "body_site": "neck",
  "signals": [
    {"type": "vibration", "direction": "sense", "sample_rate_hz": 4000, "resolution_bits": 12, "notes": "why"}
  ],
  "outputs": [
    {"modality": "haptic_vibration", "directional": true, "channels": 4, "notes": "why"}
  ],
  "intelligence": ["social", "somatic"],
  "temporal": ["anticipatory", "reactive"],
  "microcontroller": "suggested MCU",
  "connectivity": ["ble", "wifi"],
  "reasoning": "brief explanation of design choices",
  "gaps": ["things this design cannot do that the user might want"]
}"""


def spec_from_dict(data: dict) -> WearableSpec:
    return WearableSpec(
        name=data.get("name", "Unnamed"),
        body_site=BodySite(data["body_site"]),
        signals=[
            Signal(
                type=SignalType(s["type"]),
                direction=SignalDirection(s.get("direction", "sense")),
                sample_rate_hz=s.get("sample_rate_hz"),
                resolution_bits=s.get("resolution_bits"),
                notes=s.get("notes", ""),
            )
            for s in data.get("signals", [])
        ],
        outputs=[
            Output(
                modality=OutputModality(o["modality"]),
                directional=o.get("directional", False),
                channels=o.get("channels", 1),
                notes=o.get("notes", ""),
            )
            for o in data.get("outputs", [])
        ],
        intelligence=[IntelligenceClass(i) for i in data.get("intelligence", [])],
        temporal=[TemporalScope(t) for t in data.get("temporal", [])],
        microcontroller=data.get("microcontroller", ""),
        connectivity=data.get("connectivity", []),
        notes=data.get("reasoning", ""),
    )


def spec_to_prompt_context(spec: WearableSpec) -> str:
    return json.dumps(spec.to_dict(), indent=2)


def system_to_prompt_context(system: WearableSystem) -> str:
    return json.dumps(system.to_dict(), indent=2)


def gap_analysis_prompt(system: WearableSystem) -> str:
    return f"""Analyze this wearable system and identify:
1. Uncovered body sites that would add value
2. Missing signal types for the stated intelligence goals
3. Temporal gaps (can it anticipate? reflect?)
4. Output modality gaps
5. Suggested additions with reasoning

System:
{system_to_prompt_context(system)}

Coverage report:
{system.coverage_report()}

Respond with a JSON object:
{{
  "covered_well": ["list of strengths"],
  "gaps": ["list of gaps"],
  "suggestions": [
    {{"device_name": "...", "body_site": "...", "key_signals": ["..."], "reasoning": "..."}}
  ]
}}"""

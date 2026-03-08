"""AI-assisted hardware co-design using the eight-dimensional HDL grammar.

Generates full-stack wearable specifications from natural language descriptions:
hardware, electronics, firmware, interaction design, and embodiment philosophy.
AI output is parsed into grammar types and can be persisted as YAML data files.
"""
import json
import re

from delightfulos.hdl.grammar import (
    WearableSpec, WearableSystem, SITE_PROPERTIES,
)
from delightfulos.hdl.loader import library, parse_device, save_device

# ================================================================
# System Prompts
# ================================================================

CODESIGN_SYSTEM_PROMPT = """You are an Internet of Bodies (IoB) hardware co-design assistant. You help design AI wearable devices using a structured eight-dimensional grammar for embodied computing.

Your designs should be informed by embodiment philosophy — the body is not just a sensing platform, but a medium for shared experience, social negotiation, and extended cognition.

THE EIGHT DIMENSIONS:

1. BODY SITE — where on the body, with anatomical reasoning:
   head, ear, neck, chest, upper_arm, wrist, hand, finger, waist, thigh, foot, full_body
   Each site has unique anatomical affordances (nerve density, proximity to organs, social visibility).

2. SIGNAL ECOLOGY — what the device senses or emits:
   Mechanical: vibration, pressure, strain
   Bioelectric: emg, eda, ecg, eeg, eog
   Optical: camera, ir, ppg, lidar
   Audio: microphone, ultrasonic, bone_conduction_mic
   Inertial: accelerometer, gyroscope, magnetometer
   Environmental: temperature, humidity, barometric, air_quality, ambient_light, uv
   Spatial: gps, uwb, depth, radar
   Touch: capacitive, resistive
   Each signal has: direction (sense/emit/bidirectional), sample_rate_hz, resolution_bits, component, power_mw

3. OUTPUT MODALITY — how it communicates back:
   Haptic: haptic_vibration, haptic_pressure, haptic_thermal, haptic_electrotactile
   Visual: visual_led, visual_display, visual_ar, visual_projection
   Audio: audio_speaker, audio_bone_conduction
   Other: scent, none
   Each output has: directional (bool), channels (int), component, power_mw

4. INTELLIGENCE CLASS — what cognitive/somatic role:
   perception, somatic, social, cognitive, motor, affective, communicative, proprioceptive

5. TEMPORAL SCOPE — what time horizon:
   anticipatory (before events), reactive (during), reflective (after), ambient (continuous), episodic (discrete sessions)

6. ELECTRONICS — the physical computing substrate:
   microcontroller (name, cores, clock, flash, RAM)
   connectivity: wifi, ble, ble_mesh, uwb, lora, zigbee, usb, i2s, spi, i2c, uart
   power_source: lipo, coin_cell, supercapacitor, energy_harvest, usb_tethered, wireless_charging
   battery_mah, estimated_runtime_hours, voltage, total_power_mw
   pcb_notes, bom_notes (bill of materials)

7. FIRMWARE — embedded software architecture:
   framework: arduino, esp_idf, zephyr, micropython, circuitpython, bare_metal, rust_embedded
   language, data_protocol: websocket_json, websocket_binary, mqtt, ble_gatt, http_rest, osc, protobuf
   update_rate_hz, edge_processing (on-device), server_processing (cloud/edge server)
   power_modes, ota_update

8. INTERACTION & EMBODIMENT — the philosophical and social design:
   consent_model: opt_in, ambient_revocable, mutual, contextual
   social_dynamics: self, dyadic, group, environmental, asymmetric
   embodiment_principles: proprioception, interoception, exteroception, shared_perception,
     consent_play, ambient_intelligence, extended_mind, somatic_markers, umwelt, affordance
   social_signals (what social states it detects)
   signal_interpretations (what body signals mean psychologically)
   design_constraints (from embodiment philosophy)

DESIGN PHILOSOPHY:
- The body is not a passive sensor platform. It is a medium for shared experience.
- Every sensing modality has psychological and social meaning beyond its data.
- Consent is a design material, not an afterthought.
- The best wearable technology disappears into the body's own intelligence.
- Design for the umwelt — each person's subjective perceptual world.

Respond with ONLY a JSON object matching this schema:
{
  "name": "device name",
  "body_site": "neck",
  "signals": [
    {"type": "vibration", "direction": "sense", "sample_rate_hz": 4000, "resolution_bits": 12,
     "component": "specific part", "power_mw": 0.5, "notes": "why this signal, what it means for the body"}
  ],
  "outputs": [
    {"modality": "haptic_vibration", "directional": true, "channels": 4,
     "component": "LRA motors", "power_mw": 30, "notes": "why this output, what it affords"}
  ],
  "intelligence": ["social", "somatic"],
  "temporal": ["anticipatory", "reactive"],
  "electronics": {
    "microcontroller": "ESP32-S3",
    "mcu_cores": 2,
    "mcu_clock_mhz": 240,
    "mcu_flash_mb": 8,
    "mcu_ram_kb": 512,
    "connectivity": ["wifi", "ble"],
    "power_source": "lipo",
    "battery_mah": 500,
    "estimated_runtime_hours": 8,
    "voltage": 3.3,
    "total_power_mw": 150,
    "pcb_notes": "layout and manufacturing notes",
    "bom_notes": "component costs and sourcing"
  },
  "firmware": {
    "framework": "arduino",
    "language": "C++",
    "data_protocol": "websocket_json",
    "update_rate_hz": 5,
    "edge_processing": ["what runs on-device"],
    "server_processing": ["what runs on server"],
    "power_modes": ["active", "sleep"],
    "ota_update": true,
    "notes": "firmware architecture notes"
  },
  "interaction": {
    "consent_model": "mutual",
    "social_dynamics": ["dyadic"],
    "embodiment_principles": ["shared_perception", "consent_play"],
    "social_signals": ["what social states this detects"],
    "signal_interpretations": {"signal": "what it means psychologically"},
    "design_constraints": ["constraints from embodiment philosophy"],
    "notes": "interaction design philosophy"
  },
  "form_factor": {
    "form": "collar",
    "weight_grams": 45,
    "dimensions_mm": [160, 30, 12],
    "water_resistance": "IPX4",
    "materials": ["silicone", "flex PCB"],
    "notes": "physical design notes"
  },
  "reasoning": "explain your design choices across all dimensions",
  "gaps": ["things this design cannot do"],
  "psychological_notes": "how the design relates to embodiment, perception, and social dynamics"
}"""


GAP_ANALYSIS_SYSTEM_PROMPT = """You are an Internet of Bodies systems architect. You analyze multi-device wearable systems for coverage gaps across eight dimensions: body location, signal ecology, output modality, intelligence function, temporal scope, electronics, firmware, and interaction/embodiment.

Your analysis should consider:
- Anatomical coverage (which body sites are missing and why they matter)
- Signal complementarity (do the sensors work together or leave blind spots?)
- Output channel diversity (can the system communicate in multiple ways?)
- Intelligence completeness (are all relevant cognitive/somatic roles covered?)
- Temporal coverage (can it anticipate, react, reflect, and monitor?)
- Power budget (are the electronics sustainable for real use?)
- Communication architecture (do the devices form a coherent network?)
- Embodiment coherence (does the system have a consistent philosophical framework?)
- Social dynamics (what relationships does this system serve?)

Respond with ONLY a JSON object."""


# ================================================================
# Helpers
# ================================================================

def spec_from_dict(data: dict) -> WearableSpec:
    """Parse an AI-generated JSON dict into a WearableSpec using the loader's parser."""
    return parse_device(data)


def spec_to_prompt_context(spec: WearableSpec) -> str:
    return json.dumps(spec.to_dict(), indent=2)


def system_to_prompt_context(system: WearableSystem) -> str:
    return json.dumps(system.to_dict(), indent=2)


def body_site_context() -> str:
    """Generate a reference of all body sites with their properties for AI context."""
    lines = []
    for site, props in SITE_PROPERTIES.items():
        lines.append(f"- {site.value}: motion={props.motion_class}, "
                     f"visibility={props.social_visibility}, "
                     f"skin_contact={props.skin_contact}, "
                     f"nerve_density={props.nerve_density}")
        if props.anatomical_notes:
            lines.append(f"  {props.anatomical_notes}")
    return "\n".join(lines)


def gap_analysis_prompt(system: WearableSystem) -> str:
    return f"""Analyze this Internet of Bodies wearable system across all eight dimensions.

System:
{system_to_prompt_context(system)}

Coverage report:
{system.coverage_report()}

Body site reference:
{body_site_context()}

Identify:
1. Uncovered body sites that would add value and WHY anatomically
2. Missing signal types for the stated intelligence goals
3. Temporal gaps (can it anticipate? reflect? track episodes?)
4. Output modality gaps (can it communicate in enough ways?)
5. Electronics concerns (power budget, connectivity mesh, processing distribution)
6. Firmware architecture gaps (edge vs server processing balance)
7. Interaction/embodiment coherence (does the consent model work across devices?)
8. Social dynamics coverage (what relationships are underserved?)
9. Suggested additions with full reasoning

Respond with a JSON object:
{{
  "strengths": ["what the system does well across all dimensions"],
  "gaps": {{
    "anatomical": ["body coverage gaps with reasoning"],
    "signal": ["missing or redundant signals"],
    "output": ["output modality gaps"],
    "intelligence": ["cognitive/somatic role gaps"],
    "temporal": ["time horizon gaps"],
    "electronics": ["power, connectivity, or processing concerns"],
    "firmware": ["software architecture concerns"],
    "interaction": ["consent, social dynamics, embodiment gaps"]
  }},
  "suggestions": [
    {{
      "device_name": "...",
      "body_site": "...",
      "key_signals": ["..."],
      "key_outputs": ["..."],
      "intelligence_role": "...",
      "embodiment_rationale": "why this device matters for the body-as-interface vision",
      "estimated_bom": "rough cost estimate",
      "reasoning": "full design reasoning"
    }}
  ],
  "system_coherence": "overall assessment of how well the devices work together as an embodied system"
}}"""


def slugify(name: str) -> str:
    """Convert a device name to a filesystem-safe key."""
    s = name.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return s.strip('_')


def save_generated_spec(spec: WearableSpec, key: str | None = None) -> str:
    """Save an AI-generated spec to the library as a YAML file and register it.

    Returns the key used.
    """
    key = key or slugify(spec.name)
    save_device(key, spec)
    library.devices[key] = spec
    return key

# DelightfulOS — Internet of Bodies Platform

## Concept

How much control would you give your friend over your perception? Where do they end and where do we begin?

AI has made every person more insular with their perception — headphones, screens, algorithmic feeds. What if instead it facilitated physical experience, opening up our perceptions towards that of others?

DelightfulOS is a distributed operating system for real-time interactions between wearable devices under an Internet of Bodies (IoB) framework. It proposes that the most meaningful AI interfaces are not screens or speakers, but the body itself — sensed, augmented, and shared.

## Technical Position

We propose a full-stack development platform supporting Internet of Bodies hardware and interaction co-design.

To illustrate the strengths of such a strategy, we develop a modular wearable collar. This collar serves as a near-egocentric wearable sensing stack for augmented reality in live social interactions. Most AI output channels are obnoxious, noisy, and clog attention. Intuitive sensory systems are able to fuse data from disparate body signals into ambient intelligence that supports — rather than disrupts — human presence.

To position our system within a modular ecosystem, we propose a modular Hardware Description Language (HDL). This language introduces a compositional grammar for wearable hardware, enabling systematic reasoning and co-creation of design specifications. This approach facilitates the development of rich embodied systems through collaboration between humans and AI.

### Five-Dimensional Wearable Grammar

Our grammar composes AI wearables along five dimensions:

1. **Body Location** — where the device sits on the body
2. **Signal Ecology** — what it senses and from what modalities
3. **Output Modality** — how it communicates back to the wearer or environment
4. **Intelligence Function** — what class of reasoning it enables
5. **Temporal Scope** — what time horizon it operates on

#### Body-Site Classes

| Body Site | Intelligence Affordance |
|---|---|
| Head / face | Perception-centric intelligence (AR overlays, gaze, expression) |
| Ear / around-ear | Audio/attention awareness, ambient sound processing |
| Neck / collar | Speech intent, throat gestures, social proximity, consent-based interaction |
| Chest / torso | Respiration, exertion, cardiac awareness |
| Wrist | Seamless notifications, activity tracking |
| Hand / finger | Gesture, haptic feedback, fine motor |
| Waist / hip | Posture, locomotion |
| Foot / ankle | Gait, grounding |
| Full-body / garment | Distributed sensing, thermoregulation |

#### Intelligence Classes

- **Perception-centric** — glasses, cameras: what you see and how you see it
- **Somatic** — collar, chest band: what your body is doing and preparing to do
- **Social** — collar + glasses combined: how you relate to others in space

### The Collar

The collar occupies a unique body site. It is close to the mouth and throat — the primary instruments of human social communication.

**What it senses:**
- Inhalation before speaking (piezo contact mic detects pre-speech ~200ms before sound)
- Throat/jaw muscle preparation
- Neck/head posture shift before turning
- Tension changes before engagement/disengagement
- Body settling before focus
- Subtle orienting movements before interaction

**What this enables for socially-aware AI:**
- "User is about to speak" — before they make a sound
- "User is stressed and should not be overloaded" — from vocal cord tension
- "User is disengaging from the conversation" — from posture and orientation shifts

**The collar as interface:**
The collar is not just a sensor — it is a physical interface that other people interact with. Touching someone's collar creates a dialogue around consent, play, and embodiment. Your body becomes a shared control surface: tapping someone's collar changes what AR overlays appear over them, creating a tangible link between physical touch and digital perception.

**Directional haptics:**
The collar integrates haptic actuators for ambient embodied AI output. Rather than buzzing a phone in your pocket, the system can deliver directional cues at the neck — subtle enough to guide attention without disrupting presence.

### Collar Architecture

```
Front Node:
  - Piezo contact microphone (throat vibration, speech detection)
  - MEMS microphone (speech capture, transcription)
  - 3D depth camera (scene understanding, gesture, proximity)
  - IMU (head orientation, posture)
```

### AR Layer — Snap Spectacles

Snap Spectacles (5th generation) provide the perception-centric layer. We propose a shared multiplayer AR experience where AI mediates interactions between co-located people.

The Spectacles connect to DelightfulOS via Supabase Realtime (Snap Cloud), receiving:
- Per-user body state (speech, stress, engagement) at 2Hz
- AI-mediated social cues (turn-taking highlights, attention nudges)
- Live transcriptions from Gemini Live audio sessions
- Overlay commands triggered by physical interactions (collar taps)

### AI Pipeline

The AI system operates at three speeds:

| Speed | Latency | What |
|---|---|---|
| Fast | <50ms | Signal processing (piezo VAD, feature extraction) |
| Medium | <200ms | Rule-based policy (turn-taking, overload protection, collar tap response) |
| Slow | ~2s | LLM mediation (ambiguous social situations, narrative responses) |

**Inference:**
- Google Gemini Live — bidirectional real-time audio (native audio API)
- Prime Intellect — GPU-based server processing, isolated code sandboxes for agentic reasoning/tool use, inference across 100+ models

## System Architecture

```
Signal Flow:
  Body → Collar → Server → State Estimation → Policy → Spectacles → Perception

  Device -> Bus -> StateEstimator -> PolicyManager -> OutputRouter -> Device
                                          |
                                 LLM Mediator (complex situations)
```

DelightfulOS is layered:
- **OS** — typed pub/sub signal bus, device registry, state estimator (zero external deps)
- **Runtime** — policy engine (fast rules + slow AI), output routing, device lifecycle
- **Networking** — collar WebSocket, Supabase Realtime bridge, device simulator
- **AI** — signal processing, Gemini Live, Prime Intellect client, social mediator
- **XR** — platform-agnostic protocol (Spectacles active, Quest/Vision Pro/WebXR ready)
- **HDL** — five-dimensional wearable grammar, AI-assisted hardware co-design

## Demonstration

Two people in a shared space. Each wears a collar and Spectacles.

1. **Presence** — Both join. Cubes appear over each person's head (face-tracked).
2. **Body sensing** — Person A begins to speak. The collar detects speech intent before the sound. The cube glows. Body state updates flow to both Spectacles.
3. **Physical interaction** — Person B reaches over and taps Person A's collar. The cube disappears from Person B's view. Physical touch controls digital perception.
4. **Social mediation** — Both speak simultaneously. The OS detects the conflict, gives one person a subtle haptic yield signal, highlights the other as about to speak.
5. **Live AI** — Person A asks a question through their collar. Gemini responds. The transcription appears in both Spectacles as a shared AR overlay.

The interaction crosses the physical-digital boundary. Your collar is an interface that others use to shape their experience of you.

## Video Direction

Cinematic. Integrated into regular places — outdoors, a bar, walking through a city. Not a lab demo. Not boring. The technology should feel like it belongs in the world, not on a stage.

The narrative follows two people discovering what it means to share perception. The collar is visible but unobtrusive. The AR overlays are subtle. The interaction is human first, technology second.

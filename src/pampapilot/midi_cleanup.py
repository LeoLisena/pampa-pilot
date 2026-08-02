"""Reusable offline MIDI cleanup and WAV-assisted reconstruction.

The safe pass only repairs structural defects.  The reconstructed pass may
quantize lightly and correct pitches when an explicit instrument profile and
the reference audio both support the change.  The input files are never
modified.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable


@dataclass(frozen=True, slots=True)
class MidiNote:
    start_tick: int
    end_tick: int
    pitch: int
    velocity: int
    channel: int = 0
    source_index: int | None = None

    @property
    def duration_ticks(self) -> int:
        return self.end_tick - self.start_tick


@dataclass(frozen=True, slots=True)
class InstrumentProfile:
    name: str
    minimum_pitch: int | None
    maximum_pitch: int | None
    pitched: bool = True
    allow_octave_correction: bool = False


INSTRUMENT_PROFILES: dict[str, InstrumentProfile] = {
    "generic": InstrumentProfile("generic", None, None),
    "guitar": InstrumentProfile("guitar", 40, 88, allow_octave_correction=True),
    "bass": InstrumentProfile("bass", 28, 72, allow_octave_correction=True),
    "piano": InstrumentProfile("piano", 21, 108),
    "drums": InstrumentProfile("drums", 0, 127, pitched=False),
}


@dataclass(frozen=True, slots=True)
class CleanupConfig:
    """Policy for a cleanup run; values are independent of any one song."""

    bpm: float | None = None
    profile: str = "generic"
    minimum_pitch: int | None = None
    maximum_pitch: int | None = None
    quantize_division: int = 16
    quantize_tolerance_fraction: float = 0.125
    enable_quantization: bool = False
    enable_octave_correction: bool | None = None
    octave_margin_db: float = 12.0
    octave_minimum_db: float = -55.0
    propose_missing_notes: bool = True
    sample_rate: int = 22_050
    hop_length: int = 512
    alignment_window_seconds: float = 3.0


@dataclass(frozen=True, slots=True)
class ParsedMidi:
    ticks_per_beat: int
    notes: tuple[MidiNote, ...]
    tempo_events: tuple[tuple[int, int], ...]
    track_name: str
    program: int
    unmatched_note_offs: int
    hanging_note_ons: int
    time_signature: tuple[int, int] = (4, 4)
    program_events: tuple[tuple[int, Any], ...] = ()
    passthrough_events: tuple[tuple[int, Any], ...] = ()
    ignored_meta_event_count: int = 0


@dataclass(frozen=True, slots=True)
class AudioAnalysis:
    sample_rate: int
    hop_length: int
    audio_duration_seconds: float
    source_alignment_offset_seconds: float
    source_onset_alignment_score: float
    output_alignment_offset_seconds: float
    output_onset_alignment_score: float
    cqt_minimum_pitch: int
    cqt_maximum_pitch: int
    cqt_db: Any
    onset_envelope: Any


@dataclass(frozen=True, slots=True)
class CleanupPlan:
    parsed: ParsedMidi
    config: CleanupConfig
    profile: InstrumentProfile
    minimum_pitch: int
    maximum_pitch: int
    tempo_events: tuple[tuple[int, int], ...]
    analysis: AudioAnalysis
    safe_notes: tuple[MidiNote, ...]
    safe_changes: tuple[dict[str, Any], ...]
    reconstructed_notes: tuple[MidiNote, ...]
    reconstruction_changes: tuple[dict[str, Any], ...]
    missing_note_proposals: tuple[dict[str, Any], ...]


def parse_midi(path: Path) -> ParsedMidi:
    """Parse notes plus channel messages needed to retain performance data."""
    import mido

    midi = mido.MidiFile(path)
    tempo_events: list[tuple[int, int]] = []
    program_events: list[tuple[int, Any]] = []
    passthrough_events: list[tuple[int, Any]] = []
    track_name = path.stem
    program = 0
    time_signature = (4, 4)
    found_time_signature = False
    ignored_meta_event_count = 0
    found_performance_name = False

    for track in midi.tracks:
        absolute_tick = 0
        track_has_notes = any(
            message.type == "note_on" and message.velocity > 0 for message in track
        )
        for message in track:
            absolute_tick += message.time
            if message.type == "set_tempo":
                tempo_events.append((absolute_tick, message.tempo))
            elif message.type == "time_signature" and not found_time_signature:
                time_signature = (message.numerator, message.denominator)
                found_time_signature = True
            elif message.type == "track_name" and message.name:
                if track_has_notes and not found_performance_name:
                    track_name = message.name
                    found_performance_name = True
                elif not found_performance_name:
                    track_name = message.name
            elif message.type == "program_change":
                program_events.append((absolute_tick, message.copy(time=0)))
                if len(program_events) == 1:
                    program = message.program
            elif not message.is_meta and message.type not in {"note_on", "note_off"}:
                passthrough_events.append((absolute_tick, message.copy(time=0)))
            elif message.is_meta and message.type not in {
                "end_of_track",
                "set_tempo",
                "time_signature",
                "track_name",
            }:
                ignored_meta_event_count += 1

    notes: list[MidiNote] = []
    active: dict[tuple[int, int, int], list[tuple[int, int, int]]] = defaultdict(list)
    unmatched_note_offs = 0
    source_index = 0
    for track_index, track in enumerate(midi.tracks):
        absolute_tick = 0
        for message in track:
            absolute_tick += message.time
            if message.type == "note_on" and message.velocity > 0:
                active[(track_index, message.channel, message.note)].append(
                    (absolute_tick, message.velocity, source_index)
                )
                source_index += 1
            elif message.type == "note_off" or (
                message.type == "note_on" and message.velocity == 0
            ):
                key = (track_index, message.channel, message.note)
                if not active[key]:
                    unmatched_note_offs += 1
                    continue
                start_tick, velocity, note_index = active[key].pop(0)
                notes.append(
                    MidiNote(
                        start_tick=start_tick,
                        end_tick=absolute_tick,
                        pitch=message.note,
                        velocity=velocity,
                        channel=message.channel,
                        source_index=note_index,
                    )
                )

    notes.sort(key=lambda note: (note.start_tick, note.pitch, note.end_tick))
    tempo_events.sort()
    return ParsedMidi(
        ticks_per_beat=midi.ticks_per_beat,
        notes=tuple(notes),
        tempo_events=tuple(tempo_events),
        track_name=track_name,
        program=program,
        unmatched_note_offs=unmatched_note_offs,
        hanging_note_ons=sum(len(values) for values in active.values()),
        time_signature=time_signature,
        program_events=tuple(program_events),
        passthrough_events=tuple(passthrough_events),
        ignored_meta_event_count=ignored_meta_event_count,
    )


def _change(kind: str, note: MidiNote | None = None, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"kind": kind, **details}
    if note is not None:
        result["source_index"] = note.source_index
    return result


def _bpm_from_tempo(tempo: int) -> float:
    return 60_000_000.0 / tempo


def inferred_bpm(parsed: ParsedMidi) -> float:
    if not parsed.tempo_events:
        return 120.0
    return float(median(_bpm_from_tempo(tempo) for _, tempo in parsed.tempo_events))


def output_tempo_events(
    parsed: ParsedMidi, bpm: float | None
) -> tuple[tuple[int, int], ...]:
    import mido

    if bpm is not None:
        if not math.isfinite(bpm) or bpm <= 0:
            raise ValueError("bpm must be a positive finite value")
        return ((0, mido.bpm2tempo(bpm)),)
    return parsed.tempo_events or ((0, mido.bpm2tempo(120.0)),)


def safe_cleanup(
    parsed: ParsedMidi, *, target_bpm: float | None = None
) -> tuple[list[MidiNote], list[dict[str, Any]]]:
    """Remove only unambiguous duplicates and 1-2 tick same-pitch overlaps."""
    changes: list[dict[str, Any]] = []
    unique: dict[tuple[int, int, int, int], MidiNote] = {}
    for note in parsed.notes:
        key = (note.start_tick, note.end_tick, note.pitch, note.channel)
        previous = unique.get(key)
        if previous is None:
            unique[key] = note
        else:
            changes.append(
                _change(
                    "remove_exact_duplicate",
                    note,
                    kept_source_index=previous.source_index,
                )
            )

    notes = sorted(unique.values(), key=lambda note: (note.pitch, note.start_tick))
    by_key: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, note in enumerate(notes):
        by_key[(note.channel, note.pitch)].append(index)
    for indexes in by_key.values():
        for left_index, right_index in zip(indexes, indexes[1:]):
            left, right = notes[left_index], notes[right_index]
            overlap = left.end_tick - right.start_tick
            if 0 < overlap <= 2:
                notes[left_index] = replace(left, end_tick=right.start_tick)
                changes.append(
                    _change(
                        "trim_short_overlap",
                        left,
                        old_end_tick=left.end_tick,
                        new_end_tick=right.start_tick,
                        overlap_ticks=overlap,
                    )
                )

    if target_bpm is not None:
        desired = output_tempo_events(parsed, target_bpm)
        if parsed.tempo_events != desired:
            changes.append(
                {
                    "kind": "replace_tempo_map",
                    "old_event_count": len(parsed.tempo_events),
                    "new_event_count": 1,
                    "tempo_bpm": target_bpm,
                    "reason": "target tempo supplied explicitly",
                }
            )
    notes.sort(key=lambda note: (note.start_tick, note.pitch, note.end_tick))
    return notes, changes


def _tempo_converter(
    ticks_per_beat: int, tempo_events: Iterable[tuple[int, int]]
) -> Callable[[int], float]:
    import mido

    events = tuple(sorted(tempo_events))

    def convert(target_tick: int) -> float:
        seconds = 0.0
        previous_tick = 0
        tempo = 500_000
        for event_tick, event_tempo in events:
            if event_tick > target_tick:
                break
            seconds += mido.tick2second(event_tick - previous_tick, ticks_per_beat, tempo)
            previous_tick = event_tick
            tempo = event_tempo
        return seconds + mido.tick2second(target_tick - previous_tick, ticks_per_beat, tempo)

    return convert


def _alignment(
    onset_envelope: Any,
    notes: Iterable[MidiNote],
    converter: Callable[[int], float],
    *,
    sample_rate: int,
    hop_length: int,
    window_seconds: float,
) -> tuple[float, float]:
    import numpy as np

    normalized = (onset_envelope - onset_envelope.mean()) / (
        onset_envelope.std() + 1e-9
    )
    impulses = np.zeros_like(onset_envelope)
    for note in notes:
        frame = int(round(converter(note.start_tick) * sample_rate / hop_length))
        if 0 <= frame < len(impulses):
            impulses[frame] += note.velocity / 127.0
    impulses = np.convolve(impulses, np.array([0.2, 0.6, 1.0, 0.6, 0.2]), mode="same")
    impulses = (impulses - impulses.mean()) / (impulses.std() + 1e-9)
    best_score = -math.inf
    best_shift = 0
    maximum_shift = round(window_seconds * sample_rate / hop_length)
    for shift in range(-maximum_shift, maximum_shift + 1):
        if shift >= 0:
            left = impulses[: -shift or None]
            right = normalized[shift:]
        else:
            left = impulses[-shift:]
            right = normalized[:shift]
        if not len(left):
            continue
        score = float(np.mean(left * right))
        if score > best_score:
            best_score, best_shift = score, shift
    return best_shift * hop_length / sample_rate, best_score


def _profile_and_bounds(
    config: CleanupConfig, parsed: ParsedMidi
) -> tuple[InstrumentProfile, int, int]:
    if config.quantize_division <= 0:
        raise ValueError("quantize_division must be positive")
    if not 0.0 <= config.quantize_tolerance_fraction <= 0.5:
        raise ValueError("quantize_tolerance_fraction must be between 0 and 0.5")
    if config.sample_rate <= 0 or config.hop_length <= 0:
        raise ValueError("sample_rate and hop_length must be positive")
    if config.alignment_window_seconds < 0:
        raise ValueError("alignment_window_seconds cannot be negative")
    try:
        profile = INSTRUMENT_PROFILES[config.profile]
    except KeyError as error:
        choices = ", ".join(sorted(INSTRUMENT_PROFILES))
        raise ValueError(f"unknown profile {config.profile!r}; choose one of: {choices}") from error
    source_min = min((note.pitch for note in parsed.notes), default=36)
    source_max = max((note.pitch for note in parsed.notes), default=84)
    minimum = config.minimum_pitch
    if minimum is None:
        minimum = profile.minimum_pitch if profile.minimum_pitch is not None else source_min
    maximum = config.maximum_pitch
    if maximum is None:
        maximum = profile.maximum_pitch if profile.maximum_pitch is not None else source_max
    if not 0 <= minimum <= maximum <= 127:
        raise ValueError("pitch bounds must satisfy 0 <= minimum <= maximum <= 127")
    return profile, minimum, maximum


def analyze_audio_reference(
    audio_path: Path,
    parsed: ParsedMidi,
    output_tempos: tuple[tuple[int, int], ...],
    config: CleanupConfig,
    *,
    minimum_pitch: int,
    maximum_pitch: int,
    pitched: bool,
) -> AudioAnalysis:
    import librosa
    import numpy as np

    audio, observed_rate = librosa.load(audio_path, sr=config.sample_rate, mono=True)
    onset_envelope = librosa.onset.onset_strength(
        y=audio, sr=observed_rate, hop_length=config.hop_length
    )
    source_converter = _tempo_converter(parsed.ticks_per_beat, parsed.tempo_events)
    destination_converter = _tempo_converter(parsed.ticks_per_beat, output_tempos)
    source_offset, source_score = _alignment(
        onset_envelope,
        parsed.notes,
        source_converter,
        sample_rate=observed_rate,
        hop_length=config.hop_length,
        window_seconds=config.alignment_window_seconds,
    )
    output_offset, output_score = _alignment(
        onset_envelope,
        parsed.notes,
        destination_converter,
        sample_rate=observed_rate,
        hop_length=config.hop_length,
        window_seconds=config.alignment_window_seconds,
    )

    if pitched:
        nyquist_pitch = int(math.floor(librosa.hz_to_midi(observed_rate * 0.45)))
        cqt_minimum = max(
            12,
            minimum_pitch - 12,
            min((n.pitch for n in parsed.notes), default=minimum_pitch) - 12,
        )
        cqt_maximum = min(
            nyquist_pitch,
            127,
            max(
                maximum_pitch + 12,
                max((n.pitch for n in parsed.notes), default=maximum_pitch) + 12,
            ),
        )
        if cqt_maximum < cqt_minimum:
            raise ValueError("audio sample rate cannot represent the requested MIDI pitch range")
        cqt = np.abs(
            librosa.cqt(
                y=audio,
                sr=observed_rate,
                hop_length=config.hop_length,
                fmin=librosa.midi_to_hz(cqt_minimum),
                n_bins=cqt_maximum - cqt_minimum + 1,
                bins_per_octave=12,
            )
        )
        cqt_db = librosa.amplitude_to_db(cqt, ref=np.max)
    else:
        cqt_minimum, cqt_maximum = 0, -1
        cqt_db = np.empty((0, len(onset_envelope)))
    return AudioAnalysis(
        sample_rate=observed_rate,
        hop_length=config.hop_length,
        audio_duration_seconds=len(audio) / observed_rate,
        source_alignment_offset_seconds=source_offset,
        source_onset_alignment_score=source_score,
        output_alignment_offset_seconds=output_offset,
        output_onset_alignment_score=output_score,
        cqt_minimum_pitch=cqt_minimum,
        cqt_maximum_pitch=cqt_maximum,
        cqt_db=cqt_db,
        onset_envelope=onset_envelope,
    )


def _pitch_db(
    pitch: int, first_frame: int, last_frame: int, analysis: AudioAnalysis
) -> float | None:
    import numpy as np

    index = pitch - analysis.cqt_minimum_pitch
    if not 0 <= index < analysis.cqt_db.shape[0]:
        return None
    return float(np.median(analysis.cqt_db[index, first_frame:last_frame]))


def _note_audio_evidence(
    note: MidiNote,
    alternative_pitch: int,
    parsed: ParsedMidi,
    analysis: AudioAnalysis,
) -> dict[str, float | int | None]:
    converter = _tempo_converter(parsed.ticks_per_beat, parsed.tempo_events)
    start_seconds = converter(note.start_tick) + analysis.source_alignment_offset_seconds
    end_seconds = converter(note.end_tick) + analysis.source_alignment_offset_seconds
    first_frame = max(0, int(math.floor(start_seconds * analysis.sample_rate / analysis.hop_length)))
    last_frame = min(
        analysis.cqt_db.shape[1],
        max(first_frame + 1, int(math.ceil(end_seconds * analysis.sample_rate / analysis.hop_length))),
    )
    original_db = _pitch_db(note.pitch, first_frame, last_frame, analysis)
    alternative_db = _pitch_db(alternative_pitch, first_frame, last_frame, analysis)
    margin = (
        alternative_db - original_db
        if original_db is not None and alternative_db is not None
        else None
    )
    return {
        "original_pitch": note.pitch,
        "alternative_pitch": alternative_pitch,
        "original_db": original_db,
        "alternative_db": alternative_db,
        "margin_db": margin,
    }


def _nearest_grid_tick(tick: int, grid_ticks: int) -> tuple[int, int]:
    lower = tick // grid_ticks * grid_ticks
    upper = lower + grid_ticks
    nearest = lower if tick - lower <= upper - tick else upper
    return nearest, abs(nearest - tick)


def _octave_candidate(pitch: int, minimum: int, maximum: int) -> int | None:
    candidate = pitch
    while candidate < minimum:
        candidate += 12
    while candidate > maximum:
        candidate -= 12
    return candidate if candidate != pitch and minimum <= candidate <= maximum else None


def _has_pitch_collision(
    original: MidiNote, candidate_pitch: int, notes: Iterable[MidiNote]
) -> bool:
    """Reject a correction that would substantially duplicate an active note."""
    for other in notes:
        if other.source_index == original.source_index:
            continue
        if other.channel != original.channel or other.pitch != candidate_pitch:
            continue
        overlap = min(original.end_tick, other.end_tick) - max(
            original.start_tick, other.start_tick
        )
        shorter = min(original.duration_ticks, other.duration_ticks)
        if overlap > 2 and overlap >= shorter * 0.25:
            return True
    return False


def reconstruct_notes(
    notes: Iterable[MidiNote],
    parsed: ParsedMidi,
    analysis: AudioAnalysis,
    config: CleanupConfig,
    *,
    minimum_pitch: int,
    maximum_pitch: int,
) -> tuple[list[MidiNote], list[dict[str, Any]]]:
    notes = list(notes)
    profile = INSTRUMENT_PROFILES[config.profile]
    allow_octaves = (
        config.enable_octave_correction
        if config.enable_octave_correction is not None
        else profile.allow_octave_correction
    )
    grid_ticks = max(1, round(parsed.ticks_per_beat * 4 / config.quantize_division))
    tolerance_ticks = max(0, round(grid_ticks * config.quantize_tolerance_fraction))
    reconstructed: list[MidiNote] = []
    changes: list[dict[str, Any]] = []
    for original in notes:
        note = original
        candidate = _octave_candidate(note.pitch, minimum_pitch, maximum_pitch)
        if allow_octaves and profile.pitched and candidate is not None:
            evidence = _note_audio_evidence(note, candidate, parsed, analysis)
            margin = evidence["margin_db"]
            alternative_db = evidence["alternative_db"]
            supported = (
                isinstance(margin, float)
                and isinstance(alternative_db, float)
                and margin >= config.octave_margin_db
                and alternative_db >= config.octave_minimum_db
            )
            collision = _has_pitch_collision(original, candidate, notes)
            if supported and not collision:
                note = replace(note, pitch=candidate)
                changes.append(
                    _change(
                        "transpose_to_profile_range",
                        original,
                        old_pitch=original.pitch,
                        new_pitch=candidate,
                        confidence="high",
                        evidence=evidence,
                    )
                )
            elif supported and collision:
                changes.append(
                    _change(
                        "propose_pitch_correction",
                        original,
                        old_pitch=original.pitch,
                        proposed_pitch=candidate,
                        confidence="medium",
                        auto_applied=False,
                        reason="the correction would collide with an existing note",
                        evidence=evidence,
                    )
                )

        if config.enable_quantization:
            snapped_start, start_distance = _nearest_grid_tick(note.start_tick, grid_ticks)
            snapped_end, end_distance = _nearest_grid_tick(note.end_tick, grid_ticks)
            new_start = snapped_start if start_distance <= tolerance_ticks else note.start_tick
            new_end = snapped_end if end_distance <= tolerance_ticks else note.end_tick
            if new_end <= new_start:
                new_end = note.end_tick
            if new_start != note.start_tick or new_end != note.end_tick:
                changes.append(
                    _change(
                        "light_quantize",
                        original,
                        old_start_tick=note.start_tick,
                        new_start_tick=new_start,
                        old_end_tick=note.end_tick,
                        new_end_tick=new_end,
                        grid_division=config.quantize_division,
                        confidence="high",
                    )
                )
                note = replace(note, start_tick=new_start, end_tick=new_end)
        reconstructed.append(note)

    reconstructed.sort(key=lambda note: (note.start_tick, note.pitch, note.end_tick))
    return reconstructed, changes


def propose_missing_notes(
    notes: Iterable[MidiNote],
    parsed: ParsedMidi,
    analysis: AudioAnalysis,
    output_tempos: tuple[tuple[int, int], ...],
    *,
    minimum_pitch: int,
    maximum_pitch: int,
) -> list[dict[str, Any]]:
    """Report strong unmatched audio onsets without mutating the MIDI."""
    import librosa
    import numpy as np

    notes = list(notes)
    converter = _tempo_converter(parsed.ticks_per_beat, output_tempos)
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=analysis.onset_envelope,
        sr=analysis.sample_rate,
        hop_length=analysis.hop_length,
        units="frames",
        backtrack=False,
    )
    strength_threshold = float(np.percentile(analysis.onset_envelope, 85))
    midi_onsets = np.array(
        [converter(note.start_tick) + analysis.output_alignment_offset_seconds for note in notes]
    )
    lower = max(minimum_pitch, analysis.cqt_minimum_pitch)
    upper = min(maximum_pitch, analysis.cqt_maximum_pitch)
    proposals: list[dict[str, Any]] = []
    for frame in onset_frames:
        seconds = frame * analysis.hop_length / analysis.sample_rate
        if analysis.onset_envelope[frame] < strength_threshold:
            continue
        if midi_onsets.size and float(np.min(np.abs(midi_onsets - seconds))) <= 0.09:
            continue
        spectrum = np.median(
            analysis.cqt_db[:, frame : min(analysis.cqt_db.shape[1], frame + 5)], axis=1
        )
        candidates = spectrum[
            lower - analysis.cqt_minimum_pitch : upper - analysis.cqt_minimum_pitch + 1
        ]
        order = np.argsort(candidates)[::-1]
        if len(order) < 2:
            continue
        best_index, second_index = int(order[0]), int(order[1])
        best_db, second_db = float(candidates[best_index]), float(candidates[second_index])
        prominence = best_db - second_db
        if best_db < -24.0 or prominence < 7.0:
            continue
        pitch = best_index + lower
        active_pitch_classes = {
            note.pitch % 12
            for note in notes
            if converter(note.start_tick) + analysis.output_alignment_offset_seconds
            <= seconds
            <= converter(note.end_tick) + analysis.output_alignment_offset_seconds
        }
        if pitch % 12 in active_pitch_classes:
            continue
        confidence = min(
            0.99, 0.75 + prominence / 50.0 + max(0.0, best_db + 24.0) / 100.0
        )
        proposals.append(
            {
                "kind": "propose_missing_note",
                "time_seconds": seconds,
                "pitch": pitch,
                "pitch_name": librosa.midi_to_note(pitch),
                "confidence": round(confidence, 4),
                "evidence": {
                    "pitch_db": best_db,
                    "prominence_db": prominence,
                    "onset_strength": float(analysis.onset_envelope[frame]),
                },
                "auto_applied": False,
                "reason": "an audio onset can be an articulation, harmonic, or separation artifact",
            }
        )
    return proposals


def write_midi(
    path: Path,
    notes: Iterable[MidiNote],
    *,
    ticks_per_beat: int,
    bpm: float | None = None,
    tempo_events: Iterable[tuple[int, int]] = (),
    time_signature: tuple[int, int] = (4, 4),
    track_name: str,
    program: int = 0,
    program_events: Iterable[tuple[int, Any]] = (),
    passthrough_events: Iterable[tuple[int, Any]] = (),
) -> None:
    import mido

    output = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)
    conductor = mido.MidiTrack()
    conductor_events: list[tuple[int, int, Any]] = [
        (0, 0, mido.MetaMessage("track_name", name=track_name, time=0)),
        (
            0,
            1,
            mido.MetaMessage(
                "time_signature",
                numerator=time_signature[0],
                denominator=time_signature[1],
                clocks_per_click=24,
                notated_32nd_notes_per_beat=8,
                time=0,
            ),
        ),
    ]
    selected_tempos = (
        ((0, mido.bpm2tempo(bpm)),) if bpm is not None else tuple(tempo_events)
    ) or ((0, mido.bpm2tempo(120.0)),)
    conductor_events.extend(
        (tick, 2, mido.MetaMessage("set_tempo", tempo=tempo, time=0))
        for tick, tempo in selected_tempos
    )
    previous_tick = 0
    for absolute_tick, _, message in sorted(conductor_events, key=lambda event: (event[0], event[1])):
        conductor.append(message.copy(time=absolute_tick - previous_tick))
        previous_tick = absolute_tick
    conductor.append(mido.MetaMessage("end_of_track", time=0))
    output.tracks.append(conductor)

    performance = mido.MidiTrack()
    performance.append(mido.MetaMessage("track_name", name=track_name, time=0))
    events: list[tuple[int, int, int, Any]] = []
    programs = tuple(program_events)
    if programs:
        events.extend((tick, 1, 0, message.copy(time=0)) for tick, message in programs)
    else:
        events.append((0, 1, 0, mido.Message("program_change", channel=0, program=program, time=0)))
    events.extend((tick, 2, 0, message.copy(time=0)) for tick, message in passthrough_events)
    for note in notes:
        events.append(
            (
                note.start_tick,
                4,
                note.pitch,
                mido.Message(
                    "note_on",
                    channel=note.channel,
                    note=note.pitch,
                    velocity=max(1, min(127, note.velocity)),
                    time=0,
                ),
            )
        )
        events.append(
            (
                note.end_tick,
                0,
                note.pitch,
                mido.Message("note_off", channel=note.channel, note=note.pitch, velocity=0, time=0),
            )
        )
    previous_tick = 0
    for absolute_tick, _, _, message in sorted(events, key=lambda event: (event[0], event[1], event[2])):
        performance.append(message.copy(time=absolute_tick - previous_tick))
        previous_tick = absolute_tick
    performance.append(mido.MetaMessage("end_of_track", time=0))
    output.tracks.append(performance)
    path.parent.mkdir(parents=True, exist_ok=True)
    output.save(path)


def summarize_notes(notes: Iterable[MidiNote]) -> dict[str, Any]:
    notes = list(notes)
    return {
        "note_count": len(notes),
        "pitch_min": min((note.pitch for note in notes), default=None),
        "pitch_max": max((note.pitch for note in notes), default=None),
        "velocity_min": min((note.velocity for note in notes), default=None),
        "velocity_max": max((note.velocity for note in notes), default=None),
        "end_tick": max((note.end_tick for note in notes), default=0),
        "pitch_histogram": dict(sorted(Counter(note.pitch for note in notes).items())),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze_midi_file(midi_path: Path) -> dict[str, Any]:
    """Return a lightweight structural analysis without reading a WAV."""
    midi_path = Path(midi_path)
    if not midi_path.is_file():
        raise FileNotFoundError(midi_path)
    parsed = parse_midi(midi_path)
    if not parsed.notes:
        raise ValueError("the MIDI contains no complete note events")
    converter = _tempo_converter(parsed.ticks_per_beat, parsed.tempo_events)
    tempo_bpms = [_bpm_from_tempo(tempo) for _, tempo in parsed.tempo_events]
    _, safe_changes = safe_cleanup(parsed)
    return {
        "schema_version": "0.2",
        "mode": "analysis",
        "input": {
            "midi": str(midi_path.resolve()),
            "midi_sha256": _sha256(midi_path),
        },
        "structure": {
            "ticks_per_beat": parsed.ticks_per_beat,
            "time_signature": list(parsed.time_signature),
            "tempo_event_count": len(parsed.tempo_events),
            "inferred_bpm": inferred_bpm(parsed),
            "tempo_bpm_min": min(tempo_bpms, default=120.0),
            "tempo_bpm_max": max(tempo_bpms, default=120.0),
            "duration_seconds": converter(max(note.end_tick for note in parsed.notes)),
            "unmatched_note_offs": parsed.unmatched_note_offs,
            "hanging_note_ons": parsed.hanging_note_ons,
            "preserved_channel_event_count": len(parsed.program_events)
            + len(parsed.passthrough_events),
            "ignored_meta_event_count": parsed.ignored_meta_event_count,
            **summarize_notes(parsed.notes),
        },
        "safe_repair_preview": {
            "change_count": len(safe_changes),
            "change_counts": dict(Counter(change["kind"] for change in safe_changes)),
            "changes": safe_changes,
        },
        "outputs_written": False,
    }


def _resolve_config(
    config: CleanupConfig | None,
    bpm: float | None,
    profile: str | None,
) -> CleanupConfig:
    if config is not None and (bpm is not None or profile is not None):
        raise ValueError("pass either config or bpm/profile compatibility arguments")
    return config or CleanupConfig(bpm=bpm, profile=profile or "generic")


def _prepare_cleanup(
    midi_path: Path,
    audio_path: Path,
    config: CleanupConfig,
) -> CleanupPlan:
    midi_path = Path(midi_path)
    audio_path = Path(audio_path)
    if not midi_path.is_file():
        raise FileNotFoundError(midi_path)
    if not audio_path.is_file():
        raise FileNotFoundError(audio_path)
    parsed = parse_midi(midi_path)
    if not parsed.notes:
        raise ValueError("the MIDI contains no complete note events")
    profile_definition, minimum_pitch, maximum_pitch = _profile_and_bounds(
        config, parsed
    )
    tempos = output_tempo_events(parsed, config.bpm)
    safe_notes, safe_changes = safe_cleanup(parsed, target_bpm=config.bpm)
    analysis = analyze_audio_reference(
        audio_path,
        parsed,
        tempos,
        config,
        minimum_pitch=minimum_pitch,
        maximum_pitch=maximum_pitch,
        pitched=profile_definition.pitched,
    )
    reconstructed_notes, reconstruction_changes = reconstruct_notes(
        safe_notes,
        parsed,
        analysis,
        config,
        minimum_pitch=minimum_pitch,
        maximum_pitch=maximum_pitch,
    )
    proposals = (
        propose_missing_notes(
            reconstructed_notes,
            parsed,
            analysis,
            tempos,
            minimum_pitch=minimum_pitch,
            maximum_pitch=maximum_pitch,
        )
        if config.propose_missing_notes and profile_definition.pitched
        else []
    )
    return CleanupPlan(
        parsed=parsed,
        config=config,
        profile=profile_definition,
        minimum_pitch=minimum_pitch,
        maximum_pitch=maximum_pitch,
        tempo_events=tempos,
        analysis=analysis,
        safe_notes=tuple(safe_notes),
        safe_changes=tuple(safe_changes),
        reconstructed_notes=tuple(reconstructed_notes),
        reconstruction_changes=tuple(reconstruction_changes),
        missing_note_proposals=tuple(proposals),
    )


def _base_cleanup_report(
    plan: CleanupPlan, midi_path: Path, audio_path: Path
) -> dict[str, Any]:
    parsed = plan.parsed
    analysis = plan.analysis
    return {
        "schema_version": "0.2",
        "policy": "conservative_offline_midi_cleanup",
        "original_preserved": True,
        "inputs": {
            "midi": str(midi_path.resolve()),
            "midi_sha256": _sha256(midi_path),
            "audio": str(audio_path.resolve()),
            "audio_sha256": _sha256(audio_path),
        },
        "settings": {
            **asdict(plan.config),
            "resolved_profile": asdict(plan.profile),
            "resolved_pitch_range": [plan.minimum_pitch, plan.maximum_pitch],
            "effective_bpm": (
                plan.config.bpm
                if plan.config.bpm is not None
                else inferred_bpm(parsed)
            ),
            "tempo_mode": "fixed" if plan.config.bpm is not None else "preserve",
            "automatic_missing_note_additions": False,
        },
        "source": {
            "ticks_per_beat": parsed.ticks_per_beat,
            "time_signature": list(parsed.time_signature),
            "tempo_event_count": len(parsed.tempo_events),
            "unmatched_note_offs": parsed.unmatched_note_offs,
            "hanging_note_ons": parsed.hanging_note_ons,
            "preserved_channel_event_count": len(parsed.program_events)
            + len(parsed.passthrough_events),
            "ignored_meta_event_count": parsed.ignored_meta_event_count,
            **summarize_notes(parsed.notes),
        },
        "audio_alignment": {
            "duration_seconds": analysis.audio_duration_seconds,
            "source_offset_seconds": analysis.source_alignment_offset_seconds,
            "source_onset_alignment_score": analysis.source_onset_alignment_score,
            "output_offset_seconds": analysis.output_alignment_offset_seconds,
            "output_onset_alignment_score": analysis.output_onset_alignment_score,
        },
        "clean_safe": {
            "summary": summarize_notes(plan.safe_notes),
            "change_count": len(plan.safe_changes),
            "change_counts": dict(
                Counter(change["kind"] for change in plan.safe_changes)
            ),
            "changes": list(plan.safe_changes),
        },
        "reconstructed": {
            "summary": summarize_notes(plan.reconstructed_notes),
            "change_count": len(plan.reconstruction_changes),
            "change_counts": dict(
                Counter(change["kind"] for change in plan.reconstruction_changes)
            ),
            "changes": list(plan.reconstruction_changes),
            "missing_note_proposals": list(plan.missing_note_proposals),
        },
        "limitations": [
            "Audio source separation can create false harmonics and onsets.",
            "Unmatched audio onsets are proposals and are never inserted automatically.",
            "Unsupported MIDI meta events are counted but not copied to generated files.",
            "Perceptual approval still requires a later listening pass.",
        ],
    }


def preview_cleanup(
    midi_path: Path,
    audio_path: Path,
    *,
    config: CleanupConfig | None = None,
    bpm: float | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Analyze all proposed changes without writing any output file."""
    midi_path = Path(midi_path)
    audio_path = Path(audio_path)
    resolved = _resolve_config(config, bpm, profile)
    plan = _prepare_cleanup(midi_path, audio_path, resolved)
    report = _base_cleanup_report(plan, midi_path, audio_path)
    report.update({"mode": "dry_run", "outputs_written": False})
    return report


def run_cleanup(
    midi_path: Path,
    audio_path: Path,
    output_directory: Path,
    *,
    config: CleanupConfig | None = None,
    bpm: float | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Run the reusable pipeline and return its machine-readable report."""
    midi_path = Path(midi_path)
    audio_path = Path(audio_path)
    output_directory = Path(output_directory)
    resolved = _resolve_config(config, bpm, profile)
    plan = _prepare_cleanup(midi_path, audio_path, resolved)
    parsed = plan.parsed

    safe_path = output_directory / f"{midi_path.stem} - clean-safe.mid"
    reconstructed_path = output_directory / f"{midi_path.stem} - reconstructed.mid"
    report_path = output_directory / f"{midi_path.stem} - cleanup-report.json"
    common_write = {
        "ticks_per_beat": parsed.ticks_per_beat,
        "bpm": resolved.bpm,
        "tempo_events": plan.tempo_events,
        "time_signature": parsed.time_signature,
        "track_name": parsed.track_name,
        "program": parsed.program,
        "program_events": parsed.program_events,
        "passthrough_events": parsed.passthrough_events,
    }
    write_midi(safe_path, plan.safe_notes, **common_write)
    write_midi(reconstructed_path, plan.reconstructed_notes, **common_write)

    report = _base_cleanup_report(plan, midi_path, audio_path)
    report.update(
        {
            "mode": "execute",
            "outputs_written": True,
            "report_path": str(report_path.resolve()),
        }
    )
    report["clean_safe"].update(
        {"path": str(safe_path.resolve()), "sha256": _sha256(safe_path)}
    )
    report["reconstructed"].update(
        {
            "path": str(reconstructed_path.resolve()),
            "sha256": _sha256(reconstructed_path),
        }
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report

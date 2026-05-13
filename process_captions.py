#!/usr/bin/env python3
"""
process_captions.py — Convert closed caption files to CSV.

Supported formats:
  - Meeting transcript  [Speaker Name] HH:MM:SS / content
  - SRT (.srt)
  - WebVTT (.vtt)

Meeting transcript output columns:
  time, speaker, phase, content

Phase detection (from Experimenter speech, case-insensitive):
  introduction       — before the 1st "your time starts now"
  ideaGenerationOne  — after the 1st "your time starts now"
  ideaGenerationTwo  — after the 2nd "your time starts now"
  ideaSelection      — after the 3rd "your time starts now"
  debriefing         — after the last "your time is up"

Usage:
    python process_captions.py transcript.txt
    python process_captions.py transcript.txt -o out.csv
    python process_captions.py transcript.txt --phases ideaGenerationOne,ideaGenerationTwo
    python process_captions.py transcript.txt --list-phases
    python process_captions.py input.srt
    python process_captions.py input.vtt -o output.csv --include-timestamps
"""

import re
import csv
import sys
import argparse
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def parse_time_seconds(time_str: str) -> float:
    time_str = time_str.strip().replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    elif len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    return float(time_str)


def format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


# ---------------------------------------------------------------------------
# Phase detection
# ---------------------------------------------------------------------------

# Ordered sequence of transition triggers (checked against Experimenter speech).
# Each tuple: (phrase_pattern, next_phase_name)
# Transitions are consumed in order — the first match advances to the next phase.
_TRANSITIONS = [
    (re.compile(r"your time starts now", re.IGNORECASE), "ideaGenerationOne"),
    (re.compile(r"your time starts now", re.IGNORECASE), "ideaGenerationTwo"),
    (re.compile(r"your time starts now", re.IGNORECASE), "ideaSelection"),
    (re.compile(r"your time is up",      re.IGNORECASE), "debriefing"),
]

ALL_PHASES = ["introduction", "ideaGenerationOne", "ideaGenerationTwo", "ideaSelection", "debriefing"]


def assign_phases(rows: list[dict]) -> list[dict]:
    """
    Walk through rows in order and assign a 'phase' value to each one.
    Phase transitions are triggered by the Experimenter's speech matching
    the phrases defined in _TRANSITIONS, consumed in sequence.
    """
    pending = list(_TRANSITIONS)   # transitions not yet triggered
    current_phase = "introduction"

    for row in rows:
        # Check whether this row triggers the next transition
        if pending:
            pattern, next_phase = pending[0]
            if pattern.search(row["content"]):
                current_phase = next_phase
                pending.pop(0)

        row["phase"] = current_phase

    return rows


# ---------------------------------------------------------------------------
# Meeting transcript parser
# ---------------------------------------------------------------------------

_TRANSCRIPT_HEADER = re.compile(r"^\[([^\]]+)\]\s+(\d{1,2}:\d{2}:\d{2})\s*$")


def is_transcript_format(content: str) -> bool:
    for line in content.splitlines():
        if _TRANSCRIPT_HEADER.match(line.strip()):
            return True
    return False


def parse_transcript(content: str) -> list[dict]:
    rows: list[dict] = []
    current_speaker: str | None = None
    current_time: str | None = None
    current_lines: list[str] = []

    def flush():
        if current_speaker is not None and current_lines:
            text = " ".join(l.strip() for l in current_lines if l.strip())
            if text:
                rows.append({"time": current_time, "speaker": current_speaker, "content": text})

    for raw_line in content.splitlines():
        line = raw_line.strip()
        m = _TRANSCRIPT_HEADER.match(line)
        if m:
            flush()
            current_speaker = m.group(1).strip()
            current_time = m.group(2).strip()
            current_lines = []
        elif line == "":
            continue
        else:
            current_lines.append(line)

    flush()
    return rows


def write_transcript_csv(rows: list[dict], output_path: str) -> None:
    fields = ["time", "speaker", "phase", "content"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# SRT parser
# ---------------------------------------------------------------------------

def parse_srt(content: str) -> list[dict]:
    blocks = re.split(r"\n{2,}", content.strip())
    cues = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        idx_line = lines[0].strip()
        index = idx_line if re.match(r"^\d+$", idx_line) else None
        time_line_idx = 1 if index is not None else 0
        time_line = lines[time_line_idx]
        time_match = re.match(
            r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})",
            time_line,
        )
        if not time_match:
            continue
        start_s = parse_time_seconds(time_match.group(1))
        end_s = parse_time_seconds(time_match.group(2))
        text = strip_tags(" ".join(l.strip() for l in lines[time_line_idx + 1:] if l.strip()))
        cues.append({
            "index": index or str(len(cues) + 1),
            "start_time": format_time(start_s),
            "end_time": format_time(end_s),
            "start_seconds": round(start_s, 3),
            "end_seconds": round(end_s, 3),
            "duration_seconds": round(end_s - start_s, 3),
            "text": text,
        })
    return cues


# ---------------------------------------------------------------------------
# VTT parser
# ---------------------------------------------------------------------------

def parse_vtt(content: str) -> list[dict]:
    content = re.sub(r"^WEBVTT[^\n]*\n", "", content, flags=re.MULTILINE)
    for block_type in ("NOTE", "STYLE", "REGION"):
        content = re.sub(rf"{block_type}\s.*?(?=\n{{2,}}|\Z)", "", content, flags=re.DOTALL)
    cues = []
    for block in re.split(r"\n{2,}", content.strip()):
        lines = block.strip().splitlines()
        if not lines:
            continue
        time_line_idx = 0
        index = None
        if "-->" not in lines[0] and len(lines) > 1:
            index = lines[0].strip()
            time_line_idx = 1
        if time_line_idx >= len(lines):
            continue
        time_match = re.match(
            r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}|\d{1,2}:\d{2}[,\.]\d{1,3})\s*-->\s*"
            r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}|\d{1,2}:\d{2}[,\.]\d{1,3})",
            lines[time_line_idx],
        )
        if not time_match:
            continue
        start_s = parse_time_seconds(time_match.group(1))
        end_s = parse_time_seconds(time_match.group(2))
        text = strip_tags(" ".join(l.strip() for l in lines[time_line_idx + 1:] if l.strip()))
        cues.append({
            "index": index or str(len(cues) + 1),
            "start_time": format_time(start_s),
            "end_time": format_time(end_s),
            "start_seconds": round(start_s, 3),
            "end_seconds": round(end_s, 3),
            "duration_seconds": round(end_s - start_s, 3),
            "text": text,
        })
    return cues


def write_subtitle_csv(cues: list[dict], output_path: str, include_timestamps: bool) -> None:
    if include_timestamps:
        fields = ["index", "start_time", "end_time", "start_seconds", "end_seconds", "duration_seconds", "text"]
    else:
        fields = ["index", "start_time", "end_time", "duration_seconds", "text"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cues)


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

def detect_format(content: str, path: Path) -> str:
    if content.lstrip().startswith("WEBVTT") or path.suffix.lower() == ".vtt":
        return "vtt"
    if is_transcript_format(content):
        return "transcript"
    return "srt"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Convert closed caption / meeting transcript files to CSV.\n\n"
            "Meeting transcript output columns: time, speaker, phase, content\n"
            "SRT / VTT output columns:          index, start_time, end_time, duration_seconds, text"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="Input file (.txt transcript, .srt, or .vtt)")
    parser.add_argument(
        "-o", "--output",
        help="Output CSV path (default: same name as input with .csv extension)",
    )
    parser.add_argument(
        "--phases",
        help=(
            "Comma-separated list of phases to include in the output (transcript mode only).\n"
            f"Valid phases: {', '.join(ALL_PHASES)}\n"
            "Example: --phases ideaGenerationOne,ideaGenerationTwo"
        ),
    )
    parser.add_argument(
        "--list-phases",
        action="store_true",
        help="Print a summary of how many rows fall in each phase, then exit.",
    )
    parser.add_argument(
        "--include-timestamps",
        action="store_true",
        help="(SRT/VTT only) Also include raw start_seconds and end_seconds columns",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = str(args.output or input_path.with_suffix(".csv"))
    content = input_path.read_text(encoding="utf-8-sig")
    fmt = detect_format(content, input_path)

    if fmt == "transcript":
        rows = parse_transcript(content)
        if not rows:
            print("Warning: no entries found in transcript.", file=sys.stderr)
            sys.exit(1)

        rows = assign_phases(rows)

        # --list-phases: show phase breakdown and exit
        if args.list_phases:
            from collections import Counter
            counts = Counter(r["phase"] for r in rows)
            print(f"{'Phase':<22} {'Rows':>6}")
            print("-" * 30)
            for phase in ALL_PHASES:
                print(f"{phase:<22} {counts.get(phase, 0):>6}")
            print("-" * 30)
            print(f"{'TOTAL':<22} {len(rows):>6}")
            return

        # --phases: filter rows
        if args.phases:
            requested = [p.strip() for p in args.phases.split(",")]
            invalid = [p for p in requested if p not in ALL_PHASES]
            if invalid:
                print(f"Error: unknown phase(s): {', '.join(invalid)}", file=sys.stderr)
                print(f"Valid phases: {', '.join(ALL_PHASES)}", file=sys.stderr)
                sys.exit(1)
            rows = [r for r in rows if r["phase"] in requested]
            if not rows:
                print("Warning: no rows remain after phase filter.", file=sys.stderr)
                sys.exit(1)

        write_transcript_csv(rows, output_path)
        phases_present = sorted(set(r["phase"] for r in rows), key=ALL_PHASES.index)
        print(
            f"Done: {len(rows)} entries written to {output_path}\n"
            f"      Phases included: {', '.join(phases_present)}"
        )

    elif fmt == "vtt":
        cues = parse_vtt(content)
        if not cues:
            print("Warning: no cues found in VTT file.", file=sys.stderr)
            sys.exit(1)
        write_subtitle_csv(cues, output_path, args.include_timestamps)
        print(f"Done: {len(cues)} cues written to {output_path}")

    else:
        cues = parse_srt(content)
        if not cues:
            print("Warning: no cues found in SRT file.", file=sys.stderr)
            sys.exit(1)
        write_subtitle_csv(cues, output_path, args.include_timestamps)
        print(f"Done: {len(cues)} cues written to {output_path}")


if __name__ == "__main__":
    main()

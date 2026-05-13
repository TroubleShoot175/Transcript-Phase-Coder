#!/usr/bin/env python3
"""
process_captions.py — Convert closed caption files to CSV.

Supported formats:
  - Meeting transcript  [Speaker Name] HH:MM:SS / content  →  time, speaker, content
  - SRT (.srt)                                              →  index, start_time, end_time, duration_seconds, text
  - WebVTT (.vtt)                                           →  index, start_time, end_time, duration_seconds, text

Usage:
    python process_captions.py transcript.txt
    python process_captions.py transcript.txt -o output.csv
    python process_captions.py input.srt
    python process_captions.py input.vtt -o output.csv
    python process_captions.py input.srt --include-timestamps
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
    """Convert a timestamp string to total seconds (float)."""
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
    """Format total seconds as HH:MM:SS.mmm string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def strip_tags(text: str) -> str:
    """Remove HTML/VTT inline tags."""
    return re.sub(r"<[^>]+>", "", text).strip()


# ---------------------------------------------------------------------------
# Meeting transcript parser  →  time, speaker, content
# ---------------------------------------------------------------------------

# Matches lines like:  [Speaker Name] 17:03:12
_TRANSCRIPT_HEADER = re.compile(r"^\[([^\]]+)\]\s+(\d{1,2}:\d{2}:\d{2})\s*$")


def is_transcript_format(content: str) -> bool:
    for line in content.splitlines():
        if _TRANSCRIPT_HEADER.match(line.strip()):
            return True
    return False


def parse_transcript(content: str) -> list[dict]:
    """
    Parse a meeting transcript where each entry is:

        [Speaker Name] HH:MM:SS
        Content line(s)…

    Consecutive content lines belonging to the same entry are joined with a
    space. Blank lines between entries are ignored.
    """
    rows = []
    current_speaker: str | None = None
    current_time: str | None = None
    current_lines: list[str] = []

    def flush():
        if current_speaker is not None and current_lines:
            text = " ".join(l.strip() for l in current_lines if l.strip())
            if text:
                rows.append({
                    "time": current_time,
                    "speaker": current_speaker,
                    "content": text,
                })

    for raw_line in content.splitlines():
        line = raw_line.strip()
        m = _TRANSCRIPT_HEADER.match(line)
        if m:
            flush()
            current_speaker = m.group(1).strip()
            current_time = m.group(2).strip()
            current_lines = []
        elif line == "":
            # blank line — ignore, don't flush yet (next header will flush)
            continue
        else:
            current_lines.append(line)

    flush()
    return rows


def write_transcript_csv(rows: list[dict], output_path: str) -> None:
    fields = ["time", "speaker", "content"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
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
            "Supports:\n"
            "  • Meeting transcripts  [Speaker] HH:MM:SS  →  time, speaker, content\n"
            "  • SRT (.srt)                               →  index, start_time, end_time, …\n"
            "  • WebVTT (.vtt)                            →  index, start_time, end_time, …"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="Input file (.txt transcript, .srt, or .vtt)")
    parser.add_argument(
        "-o", "--output",
        help="Output CSV path (default: same name as input with .csv extension)",
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
        write_transcript_csv(rows, output_path)
        print(f"Done: {len(rows)} entries written to {output_path}  [columns: time, speaker, content]")

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

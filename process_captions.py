#!/usr/bin/env python3
"""
process_captions.py — Convert closed caption files (SRT, VTT) to CSV.

Usage:
    python process_captions.py input.srt
    python process_captions.py input.vtt -o output.csv
    python process_captions.py input.srt --include-timestamps
"""

import re
import csv
import sys
import argparse
from pathlib import Path


def parse_time(time_str: str) -> float:
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


def parse_srt(content: str) -> list[dict]:
    """Parse SRT subtitle content into a list of cue dicts."""
    blocks = re.split(r"\n{2,}", content.strip())
    cues = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        # First line: index (optional)
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

        start_seconds = parse_time(time_match.group(1))
        end_seconds = parse_time(time_match.group(2))
        text_lines = lines[time_line_idx + 1 :]
        text = " ".join(line.strip() for line in text_lines if line.strip())
        # Strip HTML tags that sometimes appear in SRT
        text = re.sub(r"<[^>]+>", "", text).strip()

        cues.append(
            {
                "index": index or str(len(cues) + 1),
                "start_time": format_time(start_seconds),
                "end_time": format_time(end_seconds),
                "start_seconds": round(start_seconds, 3),
                "end_seconds": round(end_seconds, 3),
                "duration_seconds": round(end_seconds - start_seconds, 3),
                "text": text,
            }
        )
    return cues


def parse_vtt(content: str) -> list[dict]:
    """Parse WebVTT subtitle content into a list of cue dicts."""
    # Remove the WEBVTT header and any NOTE/STYLE/REGION blocks
    content = re.sub(r"^WEBVTT[^\n]*\n", "", content, flags=re.MULTILINE)
    content = re.sub(r"NOTE\s.*?(?=\n{2,}|\Z)", "", content, flags=re.DOTALL)
    content = re.sub(r"STYLE\s.*?(?=\n{2,}|\Z)", "", content, flags=re.DOTALL)
    content = re.sub(r"REGION\s.*?(?=\n{2,}|\Z)", "", content, flags=re.DOTALL)

    blocks = re.split(r"\n{2,}", content.strip())
    cues = []
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue

        # VTT cues can optionally start with a cue identifier
        time_line_idx = 0
        index = None
        if "-->" not in lines[0] and len(lines) > 1:
            index = lines[0].strip()
            time_line_idx = 1

        if time_line_idx >= len(lines):
            continue

        time_line = lines[time_line_idx]
        time_match = re.match(
            r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}|\d{1,2}:\d{2}[,\.]\d{1,3})\s*-->\s*"
            r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}|\d{1,2}:\d{2}[,\.]\d{1,3})",
            time_line,
        )
        if not time_match:
            continue

        start_seconds = parse_time(time_match.group(1))
        end_seconds = parse_time(time_match.group(2))
        text_lines = lines[time_line_idx + 1 :]
        text = " ".join(line.strip() for line in text_lines if line.strip())
        # Strip VTT tags and cue settings
        text = re.sub(r"<[^>]+>", "", text).strip()

        cues.append(
            {
                "index": index or str(len(cues) + 1),
                "start_time": format_time(start_seconds),
                "end_time": format_time(end_seconds),
                "start_seconds": round(start_seconds, 3),
                "end_seconds": round(end_seconds, 3),
                "duration_seconds": round(end_seconds - start_seconds, 3),
                "text": text,
            }
        )
    return cues


def detect_format(content: str, path: Path) -> str:
    """Detect subtitle format from content or file extension."""
    if content.lstrip().startswith("WEBVTT"):
        return "vtt"
    if path.suffix.lower() == ".vtt":
        return "vtt"
    return "srt"


def write_csv(cues: list[dict], output_path: str, include_timestamps: bool) -> None:
    """Write cues to a CSV file."""
    if include_timestamps:
        fields = [
            "index",
            "start_time",
            "end_time",
            "start_seconds",
            "end_seconds",
            "duration_seconds",
            "text",
        ]
    else:
        fields = ["index", "start_time", "end_time", "duration_seconds", "text"]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cues)


def main():
    parser = argparse.ArgumentParser(
        description="Convert closed caption files (SRT, VTT) to CSV."
    )
    parser.add_argument("input", help="Input caption file (.srt or .vtt)")
    parser.add_argument(
        "-o",
        "--output",
        help="Output CSV file path (default: same name as input with .csv extension)",
    )
    parser.add_argument(
        "--include-timestamps",
        action="store_true",
        help="Include raw start_seconds and end_seconds columns in addition to formatted times",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    output_path = args.output or input_path.with_suffix(".csv")

    content = input_path.read_text(encoding="utf-8-sig")
    fmt = detect_format(content, input_path)

    if fmt == "vtt":
        cues = parse_vtt(content)
    else:
        cues = parse_srt(content)

    if not cues:
        print("Warning: no subtitle cues found in the input file.", file=sys.stderr)
        sys.exit(1)

    write_csv(cues, str(output_path), args.include_timestamps)
    print(f"Done: {len(cues)} cues written to {output_path}")


if __name__ == "__main__":
    main()

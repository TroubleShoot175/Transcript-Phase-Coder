# transcript-phase-coder

A command-line tool (Python and R) for converting meeting transcript closed captions into structured CSV files. Automatically detects experiment phases from key experimenter phrases and labels each utterance with its speaker, timestamp, and phase.

Designed for researchers studying **team creativity**, **group creativity**, and **collaborative brainstorming**.

---

## What it does

Given a raw closed caption transcript exported from a video conferencing tool (e.g. Zoom), the tool:

1. Parses each utterance into **time**, **speaker**, and **content**
2. Detects **experiment phase boundaries** by scanning for key phrases in the experimenter's speech
3. Labels every row with its **phase**
4. Exports a clean **CSV** ready for qualitative coding or quantitative analysis

### Output columns

| Column | Description |
|--------|-------------|
| `time` | Timestamp of the utterance (HH:MM:SS) |
| `speaker` | Speaker name or ID as it appears in the transcript |
| `phase` | Experiment phase assigned to this utterance |
| `content` | The spoken text |

---

## Supported input formats

| Format | Extension | Notes |
|--------|-----------|-------|
| Meeting transcript | `.txt` | `[Speaker Name] HH:MM:SS` followed by content — default Zoom closed caption export format |
| SubRip | `.srt` | Standard subtitle format — outputs `index, start_time, end_time, duration_seconds, text` |
| WebVTT | `.vtt` | Web video text tracks — same output structure as SRT |

The format is detected automatically from the file content.

---

## Phase detection

Phases are identified by scanning all speech for key trigger phrases. Transitions always alternate between a **start trigger** and a **stop trigger**:

| Trigger type | Recognized phrases |
|---|---|
| **Start** (begins next phase) | "your time starts now" · "your N-minute timer starts now" |
| **Stop** (ends current phase, begins break/next phase) | "your time is up" · "time is up" · "stop generating ideas" |

### Default phase sequence

```
introduction       — everything before the 1st start trigger
ideaGenerationOne  — 1st start trigger → 1st stop trigger
break              — 1st stop trigger  → 2nd start trigger
ideaGenerationTwo  — 2nd start trigger → 2nd stop trigger
break              — 2nd stop trigger  → 3rd start trigger
ideaSelection      — 3rd start trigger → 3rd stop trigger
debriefing         — 3rd stop trigger  → end of file
```

If a session is shorter (e.g. only one generation round), later phases will simply be absent. The tool will warn you which phases were not triggered in a given file.

### Custom phase names

If your study uses different phase labels or a different number of phases, pass a custom ordered list. The tool builds the transitions automatically — the first phase covers everything before the first trigger, and subsequent transitions alternate start/stop:

```bash
# Python
python process_captions.py transcript.txt \
  --phase-names "intro,generation,break,selection,debrief"

# R
Rscript process_captions.R transcript.txt \
  --phase-names "intro,generation,break,selection,debrief"
```

---

## Installation

### Python

Requires Python 3.10+. No external packages — uses the standard library only.

```bash
python process_captions.py --help
```

### R

Requires R 4.0+ and the [`optparse`](https://cran.r-project.org/package=optparse) package.

```r
install.packages("optparse")
```

```bash
Rscript process_captions.R --help
```

---

## Usage

### Basic — convert a transcript to CSV

```bash
# Python
python process_captions.py transcript.txt

# R
Rscript process_captions.R transcript.txt
```

Output is saved as `transcript.csv` in the same directory.

### Specify output path

```bash
python process_captions.py transcript.txt -o results/session1.csv
Rscript process_captions.R  transcript.txt -o results/session1.csv
```

### Inspect phase breakdown before exporting

```bash
python process_captions.py transcript.txt --list-phases
Rscript process_captions.R  transcript.txt --list-phases
```

Example output:
```
Phase                   Rows     First      Last
----------------------------------------------------
introduction              57  17:03:12  17:16:12
ideaGenerationOne        149  17:16:16  17:26:08
break                    100  17:26:26  17:44:48
ideaGenerationTwo        162  17:31:04  17:40:49
ideaSelection            186  17:44:52  17:54:59
debriefing               190  17:54:59  18:19:15
----------------------------------------------------
TOTAL                    844
```

### Export only specific phases

```bash
# Keep only the idea generation phases
python process_captions.py transcript.txt --phases ideaGenerationOne,ideaGenerationTwo
Rscript process_captions.R  transcript.txt --phases ideaGenerationOne,ideaGenerationTwo

# Keep everything except intro and debriefing
python process_captions.py transcript.txt \
  --phases ideaGenerationOne,break,ideaGenerationTwo,ideaSelection
```

### SRT / VTT subtitles (Python only)

```bash
python process_captions.py video.srt
python process_captions.py video.vtt -o output.csv --include-timestamps
```

---

## Notes for researchers

- **Consistent experimenter phrasing matters.** The tool scans all speakers' speech for trigger phrases, so any occurrence — even mid-session — will advance the phase. If your experimenter sometimes says a trigger phrase informally (e.g. "stop generating ideas" as a brief redirect), that will be treated as a phase boundary. Use `--list-phases` to verify the detected boundaries before exporting.
- **Missing phases are flagged.** If a session ends early or a trigger phrase was never said, the tool prints a warning listing the phases that were never reached.
- **"break" can appear more than once.** In the default sequence, there are two break periods. Both are labeled `break` in the CSV; filtering on `break` will include rows from both.
- The tool processes one file at a time. For batch processing of multiple session files, a simple shell loop works well:

```bash
for f in data/*.txt; do
  python process_captions.py "$f"
done
```

---

## License

MIT

#!/usr/bin/env Rscript
# process_captions.R — Convert meeting transcript files to CSV with phase labels.
#
# Phase detection uses key phrases from the experimenter's speech.
# Transitions always alternate: "starts now" → "time up" → "starts now" → ...
# The first phase covers everything before the first trigger phrase.
#
# Usage:
#   Rscript process_captions.R transcript.txt
#   Rscript process_captions.R transcript.txt -o output.csv
#   Rscript process_captions.R transcript.txt --list-phases
#   Rscript process_captions.R transcript.txt --phases ideaGenerationOne,ideaGenerationTwo
#   Rscript process_captions.R transcript.txt \
#     --phase-names "introduction,ideaGenOne,break,ideaGenTwo,selection,debrief"

.libPaths(c("~/R/library", .libPaths()))
suppressPackageStartupMessages(library(optparse))

# ── Trigger patterns ──────────────────────────────────────────────────────────

PAT_STARTS <- paste(
  "your time starts now",
  "your [0-9]+[-\\s]minute timer starts now",
  sep = "|"
)

PAT_STOP <- paste(
  "your time is up",
  "(?<!\\w)time is up",
  "stop generating ideas",
  sep = "|"
)

# ── Default phase sequence ────────────────────────────────────────────────────
# "break" appears twice because there are two inter-session breaks.

DEFAULT_PHASES <- c(
  "introduction",
  "ideaGenerationOne",
  "break",
  "ideaGenerationTwo",
  "break",
  "ideaSelection",
  "debriefing"
)

# ── Build transition table ────────────────────────────────────────────────────
# Given N phase names, produce N-1 transitions.
# Odd-numbered transitions (1, 3, 5, ...) use PAT_STARTS.
# Even-numbered transitions (2, 4, 6, ...) use PAT_STOP.

build_transitions <- function(phases) {
  n <- length(phases)
  if (n < 2) stop("At least 2 phase names are required.")
  lapply(seq_len(n - 1), function(i) {
    list(
      pattern    = if (i %% 2 == 1) PAT_STARTS else PAT_STOP,
      next_phase = phases[i + 1]
    )
  })
}

# ── Parse transcript ──────────────────────────────────────────────────────────

parse_transcript <- function(lines) {
  header_pat <- "^\\[([^\\]]+)\\]\\s+(\\d{1,2}:\\d{2}:\\d{2})\\s*$"

  rows            <- list()
  current_speaker <- NULL
  current_time    <- NULL
  current_lines   <- character(0)

  flush_entry <- function() {
    if (!is.null(current_speaker) && length(current_lines) > 0) {
      text <- paste(trimws(current_lines[nzchar(trimws(current_lines))]),
                    collapse = " ")
      if (nzchar(text)) {
        rows[[length(rows) + 1]] <<- list(
          time    = current_time,
          speaker = current_speaker,
          content = text
        )
      }
    }
  }

  for (raw_line in lines) {
    line <- trimws(raw_line)
    m    <- regexec(header_pat, line, perl = TRUE)[[1]]
    if (m[1] != -1) {
      flush_entry()
      parts           <- regmatches(line, regexec(header_pat, line, perl = TRUE))[[1]]
      current_speaker <- trimws(parts[2])
      current_time    <- parts[3]
      current_lines   <- character(0)
    } else if (nzchar(line)) {
      current_lines <- c(current_lines, line)
    }
  }
  flush_entry()

  if (length(rows) == 0) return(data.frame())

  data.frame(
    time    = sapply(rows, `[[`, "time"),
    speaker = sapply(rows, `[[`, "speaker"),
    content = sapply(rows, `[[`, "content"),
    stringsAsFactors = FALSE
  )
}

# ── Assign phases ─────────────────────────────────────────────────────────────

assign_phases <- function(df, phases) {
  transitions   <- build_transitions(phases)
  pending       <- transitions
  current_phase <- phases[1]
  phase_col     <- character(nrow(df))

  for (i in seq_len(nrow(df))) {
    if (length(pending) > 0) {
      if (grepl(pending[[1]]$pattern, df$content[i],
                ignore.case = TRUE, perl = TRUE)) {
        current_phase <- pending[[1]]$next_phase
        pending       <- pending[-1]
      }
    }
    phase_col[i] <- current_phase
  }

  df$phase <- phase_col

  # Warn about phases never reached
  triggered  <- unique(phase_col)
  still_pending_phases <- unique(sapply(pending, `[[`, "next_phase"))
  truly_missing <- setdiff(still_pending_phases, triggered)
  if (length(truly_missing) > 0) {
    message("WARNING: Phase(s) never triggered in this file: ",
            paste(truly_missing, collapse = ", "))
  }

  df
}

# ── Phase summary ─────────────────────────────────────────────────────────────

print_phase_summary <- function(df, display_phases) {
  cat(sprintf("\n%-22s %5s  %8s  %8s\n", "Phase", "Rows", "First", "Last"))
  cat(strrep("-", 52), "\n")
  for (phase in display_phases) {
    sub_df <- df[df$phase == phase, ]
    n  <- nrow(sub_df)
    ft <- if (n > 0) sub_df$time[1] else "\u2014"
    lt <- if (n > 0) sub_df$time[n] else "\u2014"
    cat(sprintf("%-22s %5d  %8s  %8s\n", phase, n, ft, lt))
  }
  cat(strrep("-", 52), "\n")
  cat(sprintf("%-22s %5d\n\n", "TOTAL", nrow(df)))
}

# ── CLI ───────────────────────────────────────────────────────────────────────

option_list <- list(
  make_option(
    c("-o", "--output"),
    type    = "character",
    default = NULL,
    help    = "Output CSV path [default: input filename with .csv extension]",
    metavar = "FILE"
  ),
  make_option(
    "--phase-names",
    type    = "character",
    default = NULL,
    metavar = "NAMES",
    help    = paste0(
      "Ordered comma-separated phase names. ",
      "The first phase covers content before the first trigger. ",
      "Transitions alternate automatically: starts-now, time-up, starts-now, ... ",
      "Default: introduction,ideaGenerationOne,break,ideaGenerationTwo,break,ideaSelection,debriefing"
    )
  ),
  make_option(
    "--phases",
    type    = "character",
    default = NULL,
    metavar = "FILTER",
    help    = "Comma-separated phases to include in the output (all others are dropped)"
  ),
  make_option(
    "--list-phases",
    action  = "store_true",
    default = FALSE,
    help    = "Print a row count and timestamp summary per phase, then exit"
  )
)

parser <- OptionParser(
  usage       = "%prog [options] input_file",
  option_list = option_list,
  description = paste(
    "Convert a meeting transcript ([Speaker] HH:MM:SS format) to a CSV file",
    "with columns: time, speaker, phase, content.",
    "\n\nPhase transitions are detected from key phrases in the transcript:",
    "\n  Start trigger : 'your time starts now' / 'your N-minute timer starts now'",
    "\n  Stop  trigger : 'your time is up' / 'time is up' / 'stop generating ideas'"
  )
)

args <- parse_args(parser, positional_arguments = 1)
opts       <- args$options
input_file <- args$args[1]

if (!file.exists(input_file)) stop("File not found: ", input_file)

# Resolve phase list
if (!is.null(opts[["phase-names"]])) {
  phases <- trimws(strsplit(opts[["phase-names"]], ",")[[1]])
  if (length(phases) < 2) stop("--phase-names requires at least 2 phase names.")
} else {
  phases <- DEFAULT_PHASES
}

display_phases <- unique(phases)   # for summary / validation (deduped, ordered)

# Parse and assign
lines <- readLines(input_file, encoding = "UTF-8", warn = FALSE)
df    <- parse_transcript(lines)
if (nrow(df) == 0) stop("No transcript entries found in: ", input_file)

df <- assign_phases(df, phases)

# --list-phases
if (isTRUE(opts[["list-phases"]])) {
  print_phase_summary(df, display_phases)
  quit(status = 0)
}

# --phases filter
if (!is.null(opts$phases)) {
  requested <- trimws(strsplit(opts$phases, ",")[[1]])
  invalid   <- setdiff(requested, display_phases)
  if (length(invalid) > 0) {
    stop("Unknown phase(s): ", paste(invalid, collapse = ", "),
         "\nValid phases: ", paste(display_phases, collapse = ", "))
  }
  df <- df[df$phase %in% requested, ]
  if (nrow(df) == 0) stop("No rows remain after applying --phases filter.")
}

# Write output
output_file <- if (!is.null(opts$output)) {
  opts$output
} else {
  sub("\\.[^.]+$", ".csv", input_file)
}

df_out <- df[, c("time", "speaker", "phase", "content")]
write.csv(df_out, output_file, row.names = FALSE)

phases_present <- display_phases[display_phases %in% unique(df$phase)]
cat(sprintf("Done: %d entries written to %s\n", nrow(df_out), output_file))
cat(sprintf("      Phases included: %s\n", paste(phases_present, collapse = ", ")))

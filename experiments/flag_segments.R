#!/usr/bin/env Rscript
# Flag traffic conditions for every road segment in a CSV.
#
# Input must contain a segment identifier and a numeric metric, for example:
#   segment_id,timestamp,mean_queue_length
#   edge_001,2025-01-01T10:00:00,4
#   edge_002,2025-01-01T10:00:00,15
#
# Thresholds are deliberately supplied by the user: appropriate congestion
# limits depend on metric units, network, and sampling interval.
#
# Usage:
#   Rscript experiments/flag_segments.R --input segment_metrics.csv \
#     --segment-column segment_id --metric mean_queue_length \
#     --warning-threshold 8 --critical-threshold 14
#
# By default, higher values are considered worse. Use --lower-is-worse for
# metrics where smaller values indicate a problem. The script retains every
# input row, adds a flag and explanation, and also writes the latest status per
# segment when --time-column is supplied.

options(stringsAsFactors = FALSE)

parse_args <- function(args) {
  result <- list(
    input = NULL,
    segment_column = "segment_id",
    metric = NULL,
    warning_threshold = NULL,
    critical_threshold = NULL,
    lower_is_worse = FALSE,
    time_column = NULL,
    output = NULL,
    verbose = FALSE
  )
  value_options <- c("input", "segment-column", "metric", "warning-threshold",
                     "critical-threshold", "time-column", "output")
  i <- 1L
  while (i <= length(args)) {
    arg <- args[[i]]
    if (arg == "--lower-is-worse") {
      result$lower_is_worse <- TRUE
      i <- i + 1L
      next
    }
    if (arg == "--verbose") {
      result$verbose <- TRUE
      i <- i + 1L
      next
    }
    if (!startsWith(arg, "--")) stop("Unexpected argument: ", arg, call. = FALSE)
    key <- substring(arg, 3L)
    if (!(key %in% value_options) || i == length(args)) {
      stop("Unknown option or missing value: ", arg, call. = FALSE)
    }
    value <- args[[i + 1L]]
    if (key == "input") result$input <- value
    else if (key == "segment-column") result$segment_column <- value
    else if (key == "metric") result$metric <- value
    else if (key == "warning-threshold") result$warning_threshold <- suppressWarnings(as.numeric(value))
    else if (key == "critical-threshold") result$critical_threshold <- suppressWarnings(as.numeric(value))
    else if (key == "time-column") result$time_column <- value
    else if (key == "output") result$output <- value
    i <- i + 2L
  }
  if (is.null(result$input)) stop("Required: --input CSV", call. = FALSE)
  if (is.null(result$metric)) stop("Required: --metric column_name", call. = FALSE)
  if (is.null(result$warning_threshold) || !is.finite(result$warning_threshold)) {
    stop("Required numeric value: --warning-threshold", call. = FALSE)
  }
  if (is.null(result$critical_threshold) || !is.finite(result$critical_threshold)) {
    stop("Required numeric value: --critical-threshold", call. = FALSE)
  }
  if (result$warning_threshold == result$critical_threshold) {
    stop("Warning and critical thresholds must differ.", call. = FALSE)
  }
  if (result$lower_is_worse && result$warning_threshold < result$critical_threshold) {
    stop("For --lower-is-worse, warning threshold should be greater than critical threshold.", call. = FALSE)
  }
  if (!result$lower_is_worse && result$warning_threshold > result$critical_threshold) {
    stop("For higher-is-worse, warning threshold should be less than critical threshold.", call. = FALSE)
  }
  result
}

flag_values <- function(values, warning_threshold, critical_threshold, lower_is_worse) {
  numeric_values <- suppressWarnings(as.numeric(as.character(values)))
  flags <- rep("NO_DATA", length(numeric_values))
  reasons <- rep("Metric is missing or not numeric", length(numeric_values))
  valid <- is.finite(numeric_values)
  if (lower_is_worse) {
    critical <- valid & numeric_values <= critical_threshold
    warning <- valid & numeric_values <= warning_threshold & !critical
  } else {
    critical <- valid & numeric_values >= critical_threshold
    warning <- valid & numeric_values >= warning_threshold & !critical
  }
  normal <- valid & !critical & !warning
  flags[normal] <- "NORMAL"
  reasons[normal] <- "Metric is within the normal range"
  flags[warning] <- "WARNING"
  reasons[warning] <- paste("Metric crossed warning threshold", warning_threshold)
  flags[critical] <- "CRITICAL"
  reasons[critical] <- paste("Metric crossed critical threshold", critical_threshold)
  list(value = numeric_values, flag = flags, reason = reasons)
}

latest_per_segment <- function(data, segment_column, time_column) {
  # Select the last row for each segment in input order when timestamps cannot
  # be parsed. Parseable times are ordered chronologically first.
  time_values <- data[[time_column]]
  parsed_time <- suppressWarnings(as.POSIXct(time_values, tz = "UTC"))
  if (all(is.na(parsed_time))) {
    order_index <- seq_len(nrow(data))
  } else {
    order_index <- order(is.na(parsed_time), parsed_time, seq_len(nrow(data)))
  }
  ordered <- data[order_index, , drop = FALSE]
  last_index <- !duplicated(as.character(ordered[[segment_column]]), fromLast = TRUE)
  result <- ordered[last_index, , drop = FALSE]
  result[order(as.character(result[[segment_column]])), , drop = FALSE]
}

run <- function(args) {
  input <- normalizePath(args$input, mustWork = TRUE)
  data <- read.csv(input, check.names = FALSE, stringsAsFactors = FALSE, na.strings = c("", "NA"))
  if (!nrow(data)) stop("Input CSV has no data rows.", call. = FALSE)
  required <- c(args$segment_column, args$metric)
  missing <- setdiff(required, names(data))
  if (length(missing)) stop("Missing required column(s): ", paste(missing, collapse = ", "), call. = FALSE)
  if (!is.null(args$time_column) && !(args$time_column %in% names(data))) {
    stop("Time column not found: ", args$time_column, call. = FALSE)
  }
  if (any(is.na(data[[args$segment_column]]) | trimws(as.character(data[[args$segment_column]])) == "")) {
    warning("Some rows have missing segment IDs; they will still be retained and flagged.", call. = FALSE)
  }

  assessed <- flag_values(data[[args$metric]], args$warning_threshold,
                          args$critical_threshold, args$lower_is_worse)
  data[[paste0(args$metric, "_numeric")]] <- assessed$value
  data$segment_flag <- assessed$flag
  data$flag_reason <- assessed$reason
  data$flag_metric <- args$metric
  data$warning_threshold <- args$warning_threshold
  data$critical_threshold <- args$critical_threshold

  output <- args$output
  if (is.null(output)) output <- sub("\\.csv$", "_flagged.csv", input, ignore.case = TRUE)
  if (identical(output, input)) stop("Output path must not overwrite input CSV.", call. = FALSE)
  output_dir <- dirname(output)
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
  write.csv(data, output, row.names = FALSE, na = "")

  if (!is.null(args$time_column)) {
    latest <- latest_per_segment(data, args$segment_column, args$time_column)
    latest_path <- sub("\\.csv$", "_latest_by_segment.csv", output, ignore.case = TRUE)
    if (identical(latest_path, output)) latest_path <- paste0(output, ".latest.csv")
    write.csv(latest, latest_path, row.names = FALSE, na = "")
    message("Latest segment snapshot: ", latest_path)
  }

  counts <- table(factor(data$segment_flag, levels = c("NORMAL", "WARNING", "CRITICAL", "NO_DATA")))
  message("Flagged rows written: ", output)
  message("Rows by flag: NORMAL=", counts[["NORMAL"]],
          ", WARNING=", counts[["WARNING"]],
          ", CRITICAL=", counts[["CRITICAL"]],
          ", NO_DATA=", counts[["NO_DATA"]])
  if (args$verbose) message("Rows processed: ", nrow(data), "; distinct segment IDs: ", length(unique(data[[args$segment_column]])))
  invisible(0L)
}

status <- tryCatch({
  run(parse_args(commandArgs(trailingOnly = TRUE)))
}, error = function(e) {
  message("Error: ", conditionMessage(e))
  2L
})
quit(save = "no", status = status)

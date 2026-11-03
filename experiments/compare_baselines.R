#!/usr/bin/env Rscript
# Compare a learned traffic controller against fixed-time, adaptive, and
# MaxPressure using actual per-seed evaluation results in a CSV.
#
# Example:
#   Rscript experiments/compare_baselines.R --input evaluation.csv
#   Rscript experiments/compare_baselines.R --input evaluation.csv \
#     --learned ia2c --higher-is-better throughput
#
# Expected columns include algorithm (or agent/controller/method), seed, and
# metrics such as mean_travel_time, mean_waiting_time, mean_queue_length, and
# throughput. Add context columns (scenario, demand_id, network, simulator,
# simulator_version, config_hash) to check comparison conditions.
# This script does not run a simulator or generate missing baseline results.

options(stringsAsFactors = FALSE)

parse_args <- function(args) {
  result <- list(
    input = NULL,
    learned = "ma2c",
    baselines = c("fixed_time", "adaptive", "maxpressure"),
    metrics = c("mean_travel_time", "mean_waiting_time", "mean_queue_length", "throughput"),
    higher_is_better = "throughput",
    match_columns = NULL,
    output_dir = NULL,
    fail_on_unfair = FALSE,
    verbose = FALSE
  )
  vector_options <- c("baselines", "metrics", "higher-is-better", "match-columns")
  i <- 1L
  while (i <= length(args)) {
    arg <- args[[i]]
    if (arg == "--fail-on-unfair") {
      result$fail_on_unfair <- TRUE
      i <- i + 1L
      next
    }
    if (arg == "--verbose") {
      result$verbose <- TRUE
      i <- i + 1L
      next
    }
    if (!startsWith(arg, "--") || i == length(args)) {
      stop("Unexpected or incomplete argument: ", arg, call. = FALSE)
    }
    key <- substring(arg, 3L)
    if (key %in% vector_options) {
      j <- i + 1L
      values <- character()
      while (j <= length(args) && !startsWith(args[[j]], "--")) {
        values <- c(values, args[[j]])
        j <- j + 1L
      }
      if (!length(values)) stop("Expected one or more values after --", key, call. = FALSE)
      if (key == "baselines") result$baselines <- values
      if (key == "metrics") result$metrics <- values
      if (key == "higher-is-better") result$higher_is_better <- values
      if (key == "match-columns") result$match_columns <- values
      i <- j
      next
    }
    value <- args[[i + 1L]]
    if (key == "input") result$input <- value
    else if (key == "learned") result$learned <- value
    else if (key == "output-dir") result$output_dir <- value
    else stop("Unknown option: --", key, call. = FALSE)
    i <- i + 2L
  }
  if (is.null(result$input)) stop("Required option missing: --input CSV", call. = FALSE)
  result
}

normalize <- function(x) gsub("[^a-z0-9]", "", tolower(trimws(as.character(x))))

aliases <- list(
  algorithm = c("algorithm", "agent", "controller", "method"),
  seed = c("seed", "randomseed", "evaluationseed"),
  mean_travel_time = c("meantraveltime", "averagetraveltime", "avgtraveltime", "traveltime"),
  mean_waiting_time = c("meanwaitingtime", "averagewaitingtime", "avgwaitingtime", "waitingtime", "waittime"),
  mean_queue_length = c("meanqueuelength", "averagequeuelength", "avgqueuelength", "queuelength"),
  throughput = c("throughput", "vehiclescompleted", "completedvehicles", "departedvehicles")
)

resolve_column <- function(headers, requested) {
  wanted <- normalize(requested)
  candidates <- aliases[[wanted]]
  if (is.null(candidates)) candidates <- wanted
  hit <- which(normalize(headers) == wanted | normalize(headers) %in% candidates)
  if (length(hit)) headers[[hit[[1L]]]] else NULL
}

finite_number <- function(value) {
  x <- suppressWarnings(as.numeric(value))
  if (length(x) != 1L || !is.finite(x)) NA_real_ else x
}

records_to_df <- function(records, fixed_columns = character()) {
  if (!length(records)) return(as.data.frame(setNames(replicate(length(fixed_columns), logical(0), simplify = FALSE), fixed_columns)))
  columns <- unique(c(fixed_columns, unlist(lapply(records, names), use.names = FALSE)))
  output <- lapply(records, function(record) {
    row <- as.list(rep(NA, length(columns)))
    names(row) <- columns
    for (name in names(record)) row[[name]] <- record[[name]]
    as.data.frame(row, stringsAsFactors = FALSE, check.names = FALSE)
  })
  do.call(rbind, output)
}

safe_mean <- function(x) {
  x <- x[is.finite(x)]
  if (!length(x)) NA_real_ else mean(x)
}
safe_sd <- function(x) {
  x <- x[is.finite(x)]
  if (length(x) < 2L) NA_real_ else stats::sd(x)
}

run_comparison <- function(args) {
  input <- normalizePath(args$input, mustWork = TRUE)
  data <- read.csv(input, check.names = FALSE, stringsAsFactors = FALSE, na.strings = c("", "NA"))
  headers <- names(data)
  algorithm_col <- resolve_column(headers, "algorithm")
  seed_col <- resolve_column(headers, "seed")
  if (is.null(algorithm_col)) stop("CSV needs an algorithm, agent, controller, or method column.", call. = FALSE)
  if (is.null(seed_col)) stop("CSV needs a seed column; per-seed pairing is required.", call. = FALSE)

  default_match <- c("seed", "scenario", "demand_id", "demand_file", "network", "simulator",
                     "simulator_version", "config_hash", "control_interval_sec", "objective", "episode_length_sec")
  requested_match <- args$match_columns
  if (is.null(requested_match)) requested_match <- default_match[vapply(default_match, function(x) !is.null(resolve_column(headers, x)), logical(1))]
  match_cols <- unique(na.omit(vapply(requested_match, function(x) {
    col <- resolve_column(headers, x)
    if (is.null(col)) {
      warning("Matching column not present; cannot check it: ", x, call. = FALSE)
      NA_character_
    } else col
  }, character(1))))
  if (!(seed_col %in% match_cols)) match_cols <- c(seed_col, match_cols)
  if (length(match_cols) == 1L) warning("Only seed is available for pairing; environment/demand/simulator fairness cannot be verified.", call. = FALSE)

  metric_cols <- setNames(vapply(args$metrics, function(metric) {
    col <- resolve_column(headers, metric)
    if (is.null(col)) {
      warning("Metric column not found; skipping: ", metric, call. = FALSE)
      NA_character_
    } else col
  }, character(1)), args$metrics)
  metric_cols <- metric_cols[!is.na(metric_cols)]
  if (!length(metric_cols)) stop("None of the requested metric columns were found.", call. = FALSE)

  alg_labels <- c(args$learned, args$baselines)
  alg_norm <- normalize(alg_labels)
  row_alg <- normalize(data[[algorithm_col]])
  relevant <- which(row_alg %in% alg_norm)
  data <- data[relevant, , drop = FALSE]
  row_alg <- row_alg[relevant]
  if (!nrow(data)) stop("No rows found for requested learned controller/baselines.", call. = FALSE)

  key_values <- lapply(match_cols, function(col) trimws(as.character(data[[col]])))
  keys <- do.call(paste, c(key_values, sep = "\034"))
  missing_key <- Reduce(`|`, lapply(key_values, function(x) is.na(x) | x == ""))
  if (any(missing_key)) warning("Ignoring rows with missing matching-key values: ", sum(missing_key), call. = FALSE)
  valid <- !missing_key
  data <- data[valid, , drop = FALSE]
  row_alg <- row_alg[valid]
  keys <- keys[valid]

  paired_records <- list()
  summary_records <- list()
  issues <- character()
  context_required <- c("scenario", "demandid", "demandfile", "network", "simulator", "simulatorversion", "confighash")
  absent_context <- setdiff(context_required, normalize(match_cols))
  fairness_status <- if (!length(absent_context)) "complete" else paste0("incomplete; absent: ", paste(absent_context, collapse = ", "))
  if (length(absent_context)) issues <- c(issues, paste("Fairness metadata columns absent:", paste(absent_context, collapse = ", ")))

  for (baseline in args$baselines) {
    baseline_norm <- normalize(baseline)
    learned_norm <- normalize(args$learned)
    if (baseline_norm == learned_norm) {
      issues <- c(issues, paste("Baseline equals learned label:", baseline))
      next
    }
    learned_idx <- which(row_alg == learned_norm)
    baseline_idx <- which(row_alg == baseline_norm)
    learned_groups <- split(learned_idx, keys[learned_idx])
    baseline_groups <- split(baseline_idx, keys[baseline_idx])
    common <- intersect(names(learned_groups), names(baseline_groups))
    pair_keys <- common[vapply(common, function(k) length(learned_groups[[k]]) == 1L && length(baseline_groups[[k]]) == 1L, logical(1))]
    duplicates <- length(common) - length(pair_keys)
    if (duplicates) issues <- c(issues, paste(args$learned, "vs", baseline, "excluded", duplicates, "duplicate matching key(s)."))
    if (!length(pair_keys)) issues <- c(issues, paste("No unambiguous paired rows found for", args$learned, "vs", baseline))

    for (metric in names(metric_cols)) {
      metric_col <- unname(metric_cols[[metric]])
      improvements <- numeric()
      learned_values <- numeric()
      baseline_values <- numeric()
      valid_n <- 0L
      is_higher <- normalize(metric) %in% normalize(args$higher_is_better)
      for (key in pair_keys) {
        li <- learned_groups[[key]][[1L]]
        bi <- baseline_groups[[key]][[1L]]
        lv <- finite_number(data[[metric_col]][li])
        bv <- finite_number(data[[metric_col]][bi])
        if (is.na(lv) || is.na(bv)) next
        delta <- if (is_higher) lv - bv else bv - lv
        improvement <- if (bv == 0) NA_real_ else delta / abs(bv) * 100
        record <- list(learned = args$learned, baseline = baseline, metric = metric,
                       higher_is_better = is_higher, learned_value = lv, baseline_value = bv,
                       improvement_percent = improvement,
                       match_status = if (length(absent_context)) "paired_metadata_incomplete" else "paired")
        for (j in seq_along(match_cols)) record[[match_cols[[j]]]] <- as.character(data[[match_cols[[j]]]][li])
        paired_records[[length(paired_records) + 1L]] <- record
        valid_n <- valid_n + 1L
        learned_values <- c(learned_values, lv)
        baseline_values <- c(baseline_values, bv)
        if (is.finite(improvement)) improvements <- c(improvements, improvement)
      }
      summary_records[[length(summary_records) + 1L]] <- list(
        learned = args$learned, baseline = baseline, metric = metric,
        direction = if (is_higher) "higher_is_better" else "lower_is_better",
        paired_n = valid_n, mean_learned = safe_mean(learned_values),
        mean_baseline = safe_mean(baseline_values),
        mean_improvement_percent = safe_mean(improvements),
        sample_sd_improvement_percent = safe_sd(improvements),
        fairness_metadata = fairness_status
      )
    }
  }

  paired_fixed <- c("learned", "baseline", "metric", "higher_is_better", "learned_value", "baseline_value", "improvement_percent", "match_status", match_cols)
  summary_fixed <- c("learned", "baseline", "metric", "direction", "paired_n", "mean_learned", "mean_baseline", "mean_improvement_percent", "sample_sd_improvement_percent", "fairness_metadata")
  paired_df <- records_to_df(paired_records, paired_fixed)
  summary_df <- records_to_df(summary_records, summary_fixed)

  out_dir <- args$output_dir
  if (is.null(out_dir)) out_dir <- file.path(dirname(input), "baseline_comparison")
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  write.csv(paired_df, file.path(out_dir, "paired_results.csv"), row.names = FALSE, na = "")
  write.csv(summary_df, file.path(out_dir, "summary.csv"), row.names = FALSE, na = "")

  format_num <- function(x) if (length(x) == 0L || is.na(x)) "NA" else sprintf("%.2f", as.numeric(x))
  report <- c(
    "# Baseline comparison report", "",
    paste0("- Input data: `", input, "`"),
    paste0("- Learned controller: `", args$learned, "`"),
    paste0("- Requested baselines: ", paste(sprintf("`%s`", args$baselines), collapse = ", ")),
    paste0("- Pairing columns: ", paste(sprintf("`%s`", match_cols), collapse = ", ")), "",
    "> Results are calculated only from rows present in the input CSV. A positive improvement means the learned controller is better in the configured metric direction. This report does not establish that the experiment itself was valid; verify simulator, demand, network, and configuration metadata.", "",
    "## Summary across paired runs", "",
    "| Learned | Baseline | Metric | Paired n | Learned mean | Baseline mean | Mean improvement (%) | Sample SD (%) | Fairness metadata |",
    "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |"
  )
  for (i in seq_len(nrow(summary_df))) {
    r <- summary_df[i, , drop = FALSE]
    report <- c(report, sprintf("| %s | %s | %s | %s | %s | %s | %s | %s | %s |",
      r$learned, r$baseline, r$metric, r$paired_n, format_num(r$mean_learned),
      format_num(r$mean_baseline), format_num(r$mean_improvement_percent),
      format_num(r$sample_sd_improvement_percent), r$fairness_metadata))
  }
  report <- c(report, "", "## Fairness and data checks", "")
  if (length(issues)) report <- c(report, paste0("- **Check:** ", issues))
  else report <- c(report, "- No pairing issues detected for the configured columns. This is not a guarantee of experimental fairness.")
  report <- c(report, "", "## Interpretation", "",
    "- Travel time, waiting time, and queue length are lower-is-better by default; throughput is higher-is-better. Override directions with `--higher-is-better`.",
    "- Lower-is-better improvement is `(baseline - learned) / |baseline| * 100`; higher-is-better improvement is `(learned - baseline) / |baseline| * 100`. Percentage is undefined when the baseline is zero.",
    "- Mean and sample standard deviation summarize per-seed percentage improvements. SD is NA with fewer than two valid paired seeds.",
    "- A seed is paired only when matching fields agree and exactly one row exists for each controller/key. Duplicate keys are excluded, not averaged.",
    "- Fairness metadata is considered complete only when scenario, demand, network, simulator, simulator version, and config hash are matching columns. Matching values do not prove identical execution.",
    "- Missing baselines or metrics are not synthesized; provide actual per-seed evaluation data before drawing comparisons.", "")
  writeLines(report, file.path(out_dir, "report.md"), useBytes = TRUE)
  message("Paired rows: ", nrow(paired_df), "; summary rows: ", nrow(summary_df))
  message("Wrote comparison outputs to ", out_dir)
  if (args$fail_on_unfair && (length(issues) || any(summary_df$paired_n == 0))) return(1L)
  0L
}

status <- tryCatch({
  args <- parse_args(commandArgs(trailingOnly = TRUE))
  if (args$verbose) message("Using base R only; no extra packages required.")
  run_comparison(args)
}, error = function(e) {
  message("Error: ", conditionMessage(e))
  2L
})
quit(save = "no", status = status)

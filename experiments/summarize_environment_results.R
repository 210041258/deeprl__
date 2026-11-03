#!/usr/bin/env Rscript
# Summarize traffic-control results across environments and algorithms.
#
# Input: a CSV with one evaluation record per environment/controller/seed, e.g.
# environment,algorithm,seed,mean_travel_time,mean_waiting_time,mean_queue_length,throughput
# large_grid,ma2c,11,120,25,8,900
# large_grid,ma2c,22,118,23,7,915
# large_grid,fixed_time,11,150,35,12,850
#
# Usage:
#   Rscript experiments/summarize_environment_results.R --input evaluation.csv
#   Rscript experiments/summarize_environment_results.R --input evaluation.csv \
#     --environment-column scenario --algorithm-column agent \
#     --metrics mean_travel_time mean_waiting_time throughput
#
# Writes environment_summary.csv and environment_report.md. Uses base R only.
# It summarizes supplied measurements; it does not run SUMO or infer missing
# results. SD is sample standard deviation and is NA when fewer than two valid
# observations exist. Ensure rows represent independent runs/seeds if you
# interpret the statistics as across-run variability.
# Rscript experiments/summarize_environment_results.R --input evaluation.csv

options(stringsAsFactors = FALSE)

parse_args <- function(args) {
  result <- list(
    input = NULL,
    environment_column = NULL,
    algorithm_column = NULL,
    seed_column = NULL,
    metrics = c("mean_travel_time", "mean_waiting_time", "mean_queue_length", "throughput"),
    group_columns = NULL,
    output_dir = NULL,
    verbose = FALSE
  )
  vector_options <- c("metrics", "group-columns")
  value_options <- c("input", "environment-column", "algorithm-column", "seed-column", "output-dir")
  i <- 1L
  while (i <= length(args)) {
    arg <- args[[i]]
    if (arg == "--verbose") {
      result$verbose <- TRUE
      i <- i + 1L
      next
    }
    if (!startsWith(arg, "--")) stop("Unexpected argument: ", arg, call. = FALSE)
    key <- substring(arg, 3L)
    if (key %in% vector_options) {
      j <- i + 1L
      values <- character()
      while (j <= length(args) && !startsWith(args[[j]], "--")) {
        values <- c(values, args[[j]])
        j <- j + 1L
      }
      if (!length(values)) stop("Expected one or more values after --", key, call. = FALSE)
      if (key == "metrics") result$metrics <- values
      if (key == "group-columns") result$group_columns <- values
      i <- j
      next
    }
    if (!(key %in% value_options) || i == length(args)) stop("Unknown option or missing value: ", arg, call. = FALSE)
    value <- args[[i + 1L]]
    if (key == "input") result$input <- value
    else if (key == "environment-column") result$environment_column <- value
    else if (key == "algorithm-column") result$algorithm_column <- value
    else if (key == "seed-column") result$seed_column <- value
    else if (key == "output-dir") result$output_dir <- value
    i <- i + 2L
  }
  if (is.null(result$input)) stop("Required option missing: --input CSV", call. = FALSE)
  result
}

normalize <- function(x) gsub("[^a-z0-9]", "", tolower(trimws(as.character(x))))

find_column <- function(headers, requested = NULL, candidates = character()) {
  if (!is.null(requested)) {
    hit <- which(tolower(headers) == tolower(requested))
    if (!length(hit)) stop("Requested column not found: ", requested, call. = FALSE)
    return(headers[[hit[[1L]]]])
  }
  hit <- which(normalize(headers) %in% normalize(candidates))
  if (length(hit)) headers[[hit[[1L]]]] else NULL
}

safe_num <- function(x) {
  value <- suppressWarnings(as.numeric(as.character(x)))
  value[!is.finite(value)] <- NA_real_
  value
}

safe_mean <- function(x) {
  x <- x[is.finite(x)]
  if (length(x)) mean(x) else NA_real_
}
safe_sd <- function(x) {
  x <- x[is.finite(x)]
  if (length(x) >= 2L) stats::sd(x) else NA_real_
}
safe_median <- function(x) {
  x <- x[is.finite(x)]
  if (length(x)) stats::median(x) else NA_real_
}
safe_min <- function(x) {
  x <- x[is.finite(x)]
  if (length(x)) min(x) else NA_real_
}
safe_max <- function(x) {
  x <- x[is.finite(x)]
  if (length(x)) max(x) else NA_real_
}

fmt <- function(x, digits = 2L) {
  if (length(x) == 0L || is.na(x) || !is.finite(as.numeric(x))) "NA" else sprintf(paste0("%.", digits, "f"), as.numeric(x))
}

run <- function(args) {
  input <- normalizePath(args$input, mustWork = TRUE)
  data <- read.csv(input, check.names = FALSE, stringsAsFactors = FALSE, na.strings = c("", "NA"))
  if (!nrow(data)) stop("Input CSV has no data rows.", call. = FALSE)
  headers <- names(data)
  env_col <- find_column(headers, args$environment_column, c("environment", "env", "scenario", "network"))
  alg_col <- find_column(headers, args$algorithm_column, c("algorithm", "agent", "controller", "method"))
  seed_col <- find_column(headers, args$seed_column, c("seed", "random_seed", "evaluation_seed"))
  if (is.null(env_col)) stop("Could not find environment column. Use --environment-column.", call. = FALSE)
  if (is.null(alg_col)) stop("Could not find algorithm/controller column. Use --algorithm-column.", call. = FALSE)
  if (is.null(seed_col)) warning("No seed column found; run counts may include repeated/non-independent observations.", call. = FALSE)

  metric_cols <- vapply(args$metrics, function(metric) {
    hit <- which(normalize(headers) == normalize(metric))
    if (length(hit)) headers[[hit[[1L]]]] else NA_character_
  }, character(1))
  metric_cols <- metric_cols[!is.na(metric_cols)]
  missing_metrics <- setdiff(args$metrics, names(metric_cols))
  if (length(missing_metrics)) warning("Metric columns not found and skipped: ", paste(missing_metrics, collapse = ", "), call. = FALSE)
  if (!length(metric_cols)) stop("None of the requested metric columns exist in the input.", call. = FALSE)

  group_cols <- args$group_columns
  if (is.null(group_cols)) {
    candidates <- c("demand_id", "network", "simulator", "simulator_version")
    group_cols <- vapply(candidates, function(candidate) {
      hit <- which(normalize(headers) == normalize(candidate))
      if (length(hit)) headers[[hit[[1L]]]] else NA_character_
    }, character(1))
    group_cols <- group_cols[!is.na(group_cols)]
  } else {
    absent <- setdiff(group_cols, headers)
    if (length(absent)) stop("Requested grouping column(s) not found: ", paste(absent, collapse = ", "), call. = FALSE)
  }
  grouping <- unique(c(env_col, alg_col, group_cols))
  if (!is.null(seed_col) && seed_col %in% grouping) grouping <- setdiff(grouping, seed_col)

  for (metric in unname(metric_cols)) data[[metric]] <- safe_num(data[[metric]])
  group_key <- do.call(interaction, c(lapply(data[grouping], function(x) {
    x <- trimws(as.character(x))
    x[is.na(x) | x == ""] <- "(missing)"
    factor(x, levels = unique(x))
  }), list(drop = TRUE, lex.order = TRUE, sep = "\034")))
  groups <- split(seq_len(nrow(data)), group_key)

  records <- lapply(groups, function(indices) {
    row <- as.list(data[indices[[1L]], grouping, drop = FALSE])
    row <- lapply(row, function(x) as.character(x[[1L]]))
    row$rows <- length(indices)
    if (!is.null(seed_col)) {
      seeds <- unique(trimws(as.character(data[[seed_col]][indices])))
      seeds <- seeds[!is.na(seeds) & seeds != ""]
      row$distinct_seeds <- length(seeds)
      if (length(seeds) != length(indices)) {
        row$duplicate_seed_rows <- length(indices) - length(seeds)
      } else {
        row$duplicate_seed_rows <- 0L
      }
    } else {
      row$distinct_seeds <- NA_integer_
      row$duplicate_seed_rows <- NA_integer_
    }
    for (metric in unname(metric_cols)) {
      values <- data[[metric]][indices]
      prefix <- metric
      row[[paste0(prefix, "_n")]] <- sum(is.finite(values))
      row[[paste0(prefix, "_mean")]] <- safe_mean(values)
      row[[paste0(prefix, "_sd")]] <- safe_sd(values)
      row[[paste0(prefix, "_median")]] <- safe_median(values)
      row[[paste0(prefix, "_min")]] <- safe_min(values)
      row[[paste0(prefix, "_max")]] <- safe_max(values)
    }
    row
  })
  summary <- do.call(rbind, lapply(records, function(x) as.data.frame(x, check.names = FALSE, stringsAsFactors = FALSE)))
  rownames(summary) <- NULL
  summary <- summary[order(summary[[env_col]], summary[[alg_col]]), , drop = FALSE]

  output_dir <- args$output_dir
  if (is.null(output_dir)) output_dir <- file.path(dirname(input), "environment_summary")
  dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)
  summary_path <- file.path(output_dir, "environment_summary.csv")
  write.csv(summary, summary_path, row.names = FALSE, na = "")

  report <- c(
    "# Environment results summary", "",
    paste0("- Input: `", input, "`"),
    paste0("- Environment column: `", env_col, "`"),
    paste0("- Algorithm/controller column: `", alg_col, "`"),
    paste0("- Seed column: `", if (is.null(seed_col)) "not available" else seed_col, "`"),
    paste0("- Grouped by: ", paste(sprintf("`%s`", grouping), collapse = ", ")),
    paste0("- Summary CSV: `", summary_path, "`"), "",
    "> This report describes the supplied data only. It does not imply that an environment was run successfully, that groups are directly comparable, or that one controller is superior. Verify simulator, network, demand, configuration, units, and seed independence.", "",
    "## Overview", "",
    paste0("- Input records: ", nrow(data)),
    paste0("- Environments: ", length(unique(data[[env_col]]))),
    paste0("- Algorithms/controllers: ", length(unique(data[[alg_col]]))),
    paste0("- Metrics summarized: ", paste(names(metric_cols), collapse = ", ")), "",
    "## Results by environment and algorithm", ""
  )
  for (env in unique(as.character(summary[[env_col]]))) {
    subset <- summary[as.character(summary[[env_col]]) == env, , drop = FALSE]
    report <- c(report, paste0("### ", env), "")
    table_header <- c("Algorithm", "Rows", "Distinct seeds")
    for (metric in unname(metric_cols)) table_header <- c(table_header, paste0(metric, " mean ± SD"))
    report <- c(report, paste0("| ", paste(table_header, collapse = " | "), " |"),
                 paste0("| ", paste(rep("---", length(table_header)), collapse = " | "), " |"))
    for (i in seq_len(nrow(subset))) {
      cells <- c(as.character(subset[[alg_col]][i]), as.character(subset$rows[i]), as.character(subset$distinct_seeds[i]))
      for (metric in unname(metric_cols)) {
        cells <- c(cells, paste0(fmt(subset[[paste0(metric, "_mean")]][i]), " ± ", fmt(subset[[paste0(metric, "_sd")]][i])))
      }
      report <- c(report, paste0("| ", paste(cells, collapse = " | "), " |"))
    }
    report <- c(report, "")
  }
  report <- c(report,
    "## Data checks and interpretation", "",
    "- Means, medians, minima, maxima, valid metric counts, and sample standard deviations are included in the CSV.",
    "- SD is `NA` if fewer than two valid values exist. Multiple rows are not necessarily independent seeds; check `distinct_seeds` and `duplicate_seed_rows`.",
    "- Comparisons are meaningful only when controllers share comparable networks, demands, simulator versions, evaluation policies, metric definitions, and seed sets.",
    "- This summary does not perform significance testing, baseline pairing, or traffic-segment flagging. Use the dedicated comparison/segment tools where appropriate.", ""
  )
  writeLines(report, file.path(output_dir, "environment_report.md"), useBytes = TRUE)
  message("Wrote summary: ", summary_path)
  message("Wrote report: ", file.path(output_dir, "environment_report.md"))
  if (args$verbose) message("Grouped ", nrow(data), " rows into ", nrow(summary), " environment/controller groups.")
  0L
}

status <- tryCatch(run(parse_args(commandArgs(trailingOnly = TRUE))), error = function(e) {
  message("Error: ", conditionMessage(e))
  2L
})
quit(save = "no", status = status)

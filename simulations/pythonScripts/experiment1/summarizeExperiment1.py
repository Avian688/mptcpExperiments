#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from summaryHelpers import (
    discover_runs,
    format_stat,
    format_value,
    prepare_output_dir,
    report_filename,
    text_table,
    write_csv,
    write_text,
)

from plotExperiment1 import (
    CONFIGS,
    MSS_BYTES,
    aggregate_summary,
    bytes_to_packets,
    common_grid,
    discover_variants,
    load_bundle,
    parse_variant_rtt_ms,
    p95,
    run_root_for,
    sample_hold_to_grid,
    summarize_bundle,
    window_mean,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize experiment 1 CSV outcomes.")
    parser.add_argument("--runs", nargs="*", type=int, help="Run IDs to include; default discovers all available runs.")
    parser.add_argument("--analysis-start", type=float, default=10.0)
    parser.add_argument("--final-window", type=float, default=60.0)
    return parser.parse_args()


def add_detailed_metrics(row: dict[str, object], bundle, analysis_start: float) -> None:
    grid = common_grid([bundle])
    for index, series in enumerate(bundle.subflows, start=1):
        sampled = sample_hold_to_grid(series, grid) / 1e6
        row[f"subflow_{index}_post_join_mbps"] = window_mean(sampled, analysis_start)

    hol = bytes_to_packets(sample_hold_to_grid(bundle.hol_blocked, grid))
    post_join_hol = hol[hol.index >= analysis_start]
    row["post_join_p95_hol_blocked_packets"] = p95(post_join_hol)
    row["post_join_max_hol_blocked_packets"] = (
        float(post_join_hol.max()) if not post_join_hol.empty else 0.0
    )


def protocol_report(label: str, rows: list[dict[str, object]], analysis_start: float, final_window: float) -> list[str]:
    mean_rows = []
    variants = {str(row["variant"]) for row in rows}
    for variant in sorted(
        variants,
        key=lambda item: (
            parse_variant_rtt_ms(item) is None,
            parse_variant_rtt_ms(item) or 0,
            item,
        ),
    ):
        group = [row for row in rows if row["variant"] == variant]
        mean_rows.append([
            variant,
            len(group),
            format_stat((row.get("post_join_app_goodput_mbps") for row in group), "Mbps"),
            format_stat((row.get("subflow_1_post_join_mbps") for row in group), "Mbps"),
            format_stat((row.get("subflow_2_post_join_mbps") for row in group), "Mbps"),
            format_stat((row.get("post_join_hol_gap_mbps") for row in group), "Mbps"),
            format_stat((row.get("post_join_p95_hol_blocked_packets") for row in group), "packets"),
        ])

    run_rows = [
        [
            row["variant"],
            row["run"],
            format_value(row.get("post_join_app_goodput_mbps")),
            format_value(row.get("app_goodput_mbps")),
            format_value(row.get("subflow_1_post_join_mbps")),
            format_value(row.get("subflow_2_post_join_mbps")),
            format_value(row.get("post_join_hol_gap_mbps")),
            format_value(row.get("post_join_p95_hol_blocked_packets")),
        ]
        for row in sorted(rows, key=lambda item: (item.get("variable_rtt_ms") or 0, item["run"]))
    ]

    return [
        f"EXPERIMENT 1 - {label}",
        "\n".join([
            "PURPOSE AND SUBFLOW GOALS",
            "Stress the scheduler with two very different paths and expose reordering / receiver HoL blocking.",
            "Path 0: fixed 20 ms RTT, 10 Mbps. It should remain usable and contribute up to 10 Mbps.",
            "Path 1: swept 20-180 ms RTT, 100 Mbps. It should carry most data once Path 0 is cwnd-limited.",
            "Connection target: approach the 110 Mbps topology ceiling without creating a persistent DSN gap.",
        ]),
        "\n".join([
            "MEASUREMENT",
            f"Primary goodput and HoL means use {analysis_start:g} s to each run's end, after the 0-5 s random start interval.",
            f"A final {final_window:g} s mean is retained as a steady-state cross-check.",
            "Connection goodput is application delivery; subflow rates are receiver-side TCP throughput vectors.",
            f"HoL bytes are reported in {MSS_BYTES}-byte packets.",
        ]),
        "MEAN OUTCOMES BY VARIABLE RTT\n" + text_table(
            ["RTT", "Runs", "App goodput", "SF rank 1", "SF rank 2", "HoL rate gap", "p95 blocked"],
            mean_rows,
        ),
        "PER-RUN OUTCOMES (rates in Mbps; HoL in packets)\n" + text_table(
            ["RTT", "Run", "Post-join app", "Final app", "SF rank 1", "SF rank 2", "HoL gap", "p95 blocked"],
            run_rows,
        ),
        "\n".join([
            "READING NOTES",
            "Subflow series are ranked by mean throughput because the extracted connection directory does not carry an explicit path ID.",
            "App goodput below the subflow sum is delivery not yet released in DSN order; combine that rate gap with blocked-packet and reinjection metrics before calling it HoL.",
        ]),
    ]


def main() -> int:
    args = parse_args()
    sim_root = Path(__file__).resolve().parents[2]
    csv_root = sim_root / "experiments" / "experiment1" / "csvs"
    out_dir = sim_root / "plots" / "experiment1" / "summaries"
    runs = discover_runs(csv_root, args.runs)
    if not runs:
        print(f"no extracted runs found under {csv_root}")
        return 1

    rows: list[dict[str, object]] = []
    incomplete: list[str] = []
    for variant in discover_variants(csv_root, runs):
        for protocol, scheduler, label in CONFIGS:
            for run in runs:
                if not run_root_for(csv_root, protocol, scheduler, variant, run).is_dir():
                    continue
                bundle = load_bundle(csv_root, protocol, scheduler, label, variant, run)
                if bundle is None:
                    incomplete.append(f"{label} {variant} run{run}")
                    continue
                row = summarize_bundle(bundle, args.final_window, args.analysis_start)
                if not row:
                    incomplete.append(f"{label} {variant} run{run}")
                    continue
                add_detailed_metrics(row, bundle, args.analysis_start)
                rows.append(row)

    if not rows:
        print(f"no complete experiment 1 outcomes found under {csv_root}")
        return 1

    prepare_output_dir(out_dir)
    write_csv(out_dir / "run_metrics.csv", rows)
    aggregate_rows = aggregate_summary(pd.DataFrame(rows)).to_dict(orient="records")
    write_csv(out_dir / "aggregate_metrics.csv", aggregate_rows)

    overview_rows = []
    for protocol, scheduler, label in CONFIGS:
        group = [row for row in rows if row["protocol"] == protocol and row["scheduler"] == scheduler]
        if not group:
            continue
        write_text(
            out_dir / report_filename(f"{protocol}_{scheduler}"),
            protocol_report(label, group, args.analysis_start, args.final_window),
        )
        overview_rows.append([
            label,
            len({int(row["run"]) for row in group}),
            len({str(row["variant"]) for row in group}),
            format_stat((row.get("post_join_app_goodput_mbps") for row in group), "Mbps"),
            format_stat((row.get("post_join_hol_gap_mbps") for row in group), "Mbps"),
        ])

    sections = [
        "EXPERIMENT 1 OUTCOME OVERVIEW",
        f"Discovered run IDs: {', '.join(map(str, runs))}",
        text_table(["Configuration", "Runs", "RTTs", "App goodput", "HoL rate gap"], overview_rows),
    ]
    if incomplete:
        sections.append("INCOMPLETE DATA\n" + "\n".join(f"- {item}" for item in incomplete))
    sections.append("Detailed per-run and aggregate values are in run_metrics.csv and aggregate_metrics.csv.")
    write_text(out_dir / "overview.txt", sections)
    print(f"wrote experiment 1 outcome summaries under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

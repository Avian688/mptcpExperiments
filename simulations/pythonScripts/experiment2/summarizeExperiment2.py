#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from summaryHelpers import (
    available_protocols,
    discover_runs,
    format_stat,
    format_value,
    mean_std,
    prepare_output_dir,
    report_filename,
    text_table,
    write_csv,
    write_text,
)

from plotExperiment2 import (
    MSS_BYTES,
    PATH_CAPACITY_MBPS,
    PATH_QUEUE_MODULES,
    PROTOCOLS,
    TOTAL_PATH_CAPACITY_MBPS,
    USER_PATH_IDS,
    USERS,
    aggregate_summary,
    build_run_summary,
    common_grid,
    final_mean,
    load_bundle,
    resample,
)


IDEAL_USER_MBPS = TOTAL_PATH_CAPACITY_MBPS / len(USERS)
PRIVATE_PATH_CAPACITY_MBPS = PATH_CAPACITY_MBPS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize experiment 2 CSV outcomes.")
    parser.add_argument("--runs", nargs="*", type=int, help="Run IDs to include; default discovers all available runs.")
    parser.add_argument("--analysis-start", type=float, default=10.0)
    parser.add_argument("--final-window", type=float, default=10.0)
    return parser.parse_args()


def ideal_subflow_rate(user: str, path: int) -> float:
    if user == "A":
        return IDEAL_USER_MBPS / 4
    if path >= 5:
        return PRIVATE_PATH_CAPACITY_MBPS
    return (IDEAL_USER_MBPS - 2 * PRIVATE_PATH_CAPACITY_MBPS) / 2


def add_subflow_metrics(row: dict[str, object], bundle, analysis_start: float, final_window: float) -> None:
    grid = common_grid([bundle])
    final_start = max(float(grid.max()) - final_window, float(grid.min()))
    for user, _index, _description in USERS:
        for path, throughput, cwnd in zip(
            USER_PATH_IDS[user], bundle.subflow_throughput[user], bundle.subflow_cwnd[user]
        ):
            sampled_throughput = resample(throughput, grid) / 1e6
            sampled_cwnd = resample(cwnd, grid) / MSS_BYTES
            row[f"user_{user}_path_{path}_goodput_mbps"] = final_mean(
                sampled_throughput, analysis_start
            )
            row[f"user_{user}_path_{path}_final_goodput_mbps"] = final_mean(
                sampled_throughput, final_start
            )
            row[f"user_{user}_path_{path}_final_cwnd_packets"] = final_mean(
                sampled_cwnd, final_start
            )


def protocol_report(label: str, rows: list[dict[str, object]], analysis_start: float, final_window: float) -> list[str]:
    run_rows = []
    for row in sorted(rows, key=lambda item: int(item["run"])):
        run_rows.append([
            row["run"],
            format_value(row.get("user_A_run_average_goodput_mbps")),
            format_value(row.get("user_B_run_average_goodput_mbps")),
            format_value(row.get("user_C_run_average_goodput_mbps")),
            format_value(row.get("run_average_aggregate_goodput_mbps")),
            format_value(row.get("run_average_jain_fairness"), digits=3),
            format_value(row.get("run_average_a_vs_bc_mean_ratio"), digits=3),
        ])

    subflow_rows = []
    for user, _index, description in USERS:
        for path in USER_PATH_IDS[user]:
            key = f"user_{user}_path_{path}_goodput_mbps"
            final_key = f"user_{user}_path_{path}_final_goodput_mbps"
            target = ideal_subflow_rate(user, path)
            achieved, _deviation, _count = mean_std(row.get(key) for row in rows)
            subflow_rows.append([
                f"{user}/path {path}",
                description,
                format_value(target),
                format_stat((row.get(key) for row in rows), "Mbps"),
                format_value(achieved - target if np.isfinite(achieved) else None),
                format_stat((row.get(final_key) for row in rows), "Mbps"),
            ])

    queue_rows = [
        [
            path,
            "shared" if path <= 4 else "private",
            format_stat((row.get(f"path_{path}_post_join_queue_packets") for row in rows), "packets"),
        ]
        for path in PATH_QUEUE_MODULES
    ]

    return [
        f"EXPERIMENT 2 - {label}",
        "\n".join([
            "PURPOSE AND CONNECTION GOALS",
            "Test aggregate fairness when every connection has four edge-disjoint subflows but different path sharing.",
            "A uses paths 1-4 and every path is shared. B uses shared 1-2 plus private 5-6. C uses shared 3-4 plus private 7-8.",
            f"Ideal aggregate allocation: A = B = C = {IDEAL_USER_MBPS:.2f} Mbps, Jain fairness = 1, total = {TOTAL_PATH_CAPACITY_MBPS:.0f} Mbps.",
            f"Ideal symmetric subflow allocation: A gets {ideal_subflow_rate('A', 1):.2f} Mbps on each shared path; "
            f"B/C get {ideal_subflow_rate('B', 1):.2f} Mbps on each shared path and "
            f"{PRIVATE_PATH_CAPACITY_MBPS:.0f} Mbps on each private path.",
            "This fills every path while preventing B and C from taking an extra aggregate share merely because they have private capacity.",
        ]),
        "\n".join([
            "MEASUREMENT",
            f"Primary outcomes use {analysis_start:g} s to each run's end, after every 0-5 s random connection start.",
            f"The final {final_window:g} s means are shown as a convergence cross-check.",
            "Connection values are application goodput; subflow values are receiver-side TCP throughput vectors.",
            "All reported variation is population standard deviation across the runs that actually exist.",
        ]),
        "PER-RUN CONNECTION OUTCOMES (Mbps)\n" + text_table(
            ["Run", "A", "B", "C", "Aggregate", "Jain", "A/mean(B,C)"], run_rows
        ),
        "SUBFLOW OUTCOMES (primary window)\n" + text_table(
            ["Subflow", "Role", "Target", "Achieved", "Gap", "Final-window"], subflow_rows
        ),
        "QUEUE OCCUPANCY\n" + text_table(["Path", "Role", "Post-join mean"], queue_rows),
        "\n".join([
            "PROTOCOL MEAN",
            f"A goodput: {format_stat((row.get('user_A_run_average_goodput_mbps') for row in rows), 'Mbps')}",
            f"B goodput: {format_stat((row.get('user_B_run_average_goodput_mbps') for row in rows), 'Mbps')}",
            f"C goodput: {format_stat((row.get('user_C_run_average_goodput_mbps') for row in rows), 'Mbps')}",
            f"Aggregate: {format_stat((row.get('run_average_aggregate_goodput_mbps') for row in rows), 'Mbps')}",
            f"Jain fairness: {format_stat((row.get('run_average_jain_fairness') for row in rows), digits=3)}",
            f"A / mean(B,C): {format_stat((row.get('run_average_a_vs_bc_mean_ratio') for row in rows), digits=3)}",
        ]),
    ]


def main() -> int:
    args = parse_args()
    sim_root = Path(__file__).resolve().parents[2]
    csv_root = sim_root / "experiments" / "experiment2" / "csvs"
    out_dir = sim_root / "plots" / "experiment2" / "summaries"
    runs = discover_runs(csv_root, args.runs)
    if not runs:
        print(f"no extracted runs found under {csv_root}")
        return 1

    rows: list[dict[str, object]] = []
    incomplete: list[str] = []
    protocol_specs = available_protocols(csv_root, PROTOCOLS)
    for protocol, label in protocol_specs:
        for run in runs:
            if not (csv_root / protocol / f"run{run}").is_dir():
                continue
            bundle = load_bundle(csv_root, protocol, label, run)
            if bundle is None:
                incomplete.append(f"{label} run{run}")
                continue
            row = build_run_summary(bundle, args.final_window, args.analysis_start)
            if not row:
                incomplete.append(f"{label} run{run}")
                continue
            add_subflow_metrics(row, bundle, args.analysis_start, args.final_window)
            rows.append(row)

    if not rows:
        print(f"no complete experiment 2 outcomes found under {csv_root}")
        return 1

    prepare_output_dir(out_dir)
    write_csv(out_dir / "run_metrics.csv", rows)
    aggregate_rows = aggregate_summary(pd.DataFrame(rows)).to_dict(orient="records")
    write_csv(out_dir / "aggregate_metrics.csv", aggregate_rows)

    overview_rows = []
    for protocol, label in protocol_specs:
        group = [row for row in rows if row["protocol"] == protocol]
        if not group:
            continue
        write_text(
            out_dir / report_filename(protocol),
            protocol_report(label, group, args.analysis_start, args.final_window),
        )
        overview_rows.append([
            label,
            len(group),
            format_stat((row.get("user_A_run_average_goodput_mbps") for row in group), "Mbps"),
            format_stat((row.get("user_B_run_average_goodput_mbps") for row in group), "Mbps"),
            format_stat((row.get("user_C_run_average_goodput_mbps") for row in group), "Mbps"),
            format_stat((row.get("run_average_aggregate_goodput_mbps") for row in group), "Mbps"),
            format_stat((row.get("run_average_jain_fairness") for row in group), digits=3),
        ])

    sections = [
        "EXPERIMENT 2 OUTCOME OVERVIEW",
        f"Discovered run IDs: {', '.join(map(str, runs))}",
        text_table(["Protocol", "Runs", "A", "B", "C", "Aggregate", "Jain"], overview_rows),
    ]
    if incomplete:
        sections.append("INCOMPLETE DATA\n" + "\n".join(f"- {item}" for item in incomplete))
    sections.append("Detailed per-run and aggregate values are in run_metrics.csv and aggregate_metrics.csv.")
    write_text(out_dir / "overview.txt", sections)
    print(f"wrote experiment 2 outcome summaries under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

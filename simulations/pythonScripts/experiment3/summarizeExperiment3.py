#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from summaryHelpers import (
    available_protocols,
    discover_runs,
    format_stat,
    format_value,
    prepare_output_dir,
    report_filename,
    text_table,
    write_csv,
    write_text,
)

from plotExperiment3 import (
    BLUE_USERS,
    CONNECTIONS,
    IDEAL_AGGREGATE_MBPS,
    IDEAL_PROBE_PER_CONNECTION_MBPS,
    IDEAL_TOTAL_PROBE_MBPS,
    MSS_BYTES,
    PROTOCOLS,
    T_CAPACITY_MBPS,
    USER_COUNT,
    USERS_PER_TYPE,
    X_CAPACITY_MBPS,
    aggregate_summary,
    build_run_summary,
    common_grid,
    load_bundle,
    mean_mbps,
    resample,
)


IDEAL_CONNECTION_MBPS = IDEAL_AGGREGATE_MBPS / USER_COUNT
IDEAL_BLUE_X1_TOTAL_MBPS = X_CAPACITY_MBPS - IDEAL_TOTAL_PROBE_MBPS
IDEAL_BLUE_X2_TOTAL_MBPS = IDEAL_AGGREGATE_MBPS / 2 - IDEAL_BLUE_X1_TOTAL_MBPS
IDEAL_RED_Y1_TOTAL_MBPS = IDEAL_TOTAL_PROBE_MBPS
IDEAL_RED_Y2_TOTAL_MBPS = IDEAL_AGGREGATE_MBPS / 2 - IDEAL_RED_Y1_TOTAL_MBPS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize experiment 3 CSV outcomes.")
    parser.add_argument("--runs", nargs="*", type=int, help="Run IDs to include; default discovers all available runs.")
    parser.add_argument("--analysis-start", type=float, default=100.0)
    return parser.parse_args()


def add_connection_metrics(row: dict[str, object], bundle, analysis_start: float) -> None:
    grid = common_grid([bundle])
    grid = grid[grid >= analysis_start]
    for user in range(USER_COUNT):
        _name, path_names = CONNECTIONS[user]
        for index, path_name in enumerate(path_names):
            key = path_name.split(":", maxsplit=1)[0]
            row[f"connection_{user}_{key}_mbps"] = mean_mbps(bundle.subflows[user][index], grid)
            row[f"connection_{user}_{key}_cwnd_packets"] = float(
                resample(bundle.cwnd[user][index], grid).mean() / MSS_BYTES
            )


def connection_label(user: int) -> str:
    return f"B{user + 1}" if user in BLUE_USERS else f"R{user - USERS_PER_TYPE + 1}"


def protocol_report(label: str, rows: list[dict[str, object]], analysis_start: float) -> list[str]:
    run_rows = [
        [
            row["run"],
            format_value(row.get("blue_total_goodput_mbps")),
            format_value(row.get("red_total_goodput_mbps")),
            format_value(row.get("aggregate_goodput_mbps")),
            format_value(row.get("red_y1_mbps")),
            format_value(row.get("x_load_mbps")),
            format_value(row.get("t_load_mbps")),
        ]
        for row in sorted(rows, key=lambda item: int(item["run"]))
    ]

    connection_rows = []
    for user in range(USER_COUNT):
        name, path_names = CONNECTIONS[user]
        first = path_names[0].split(":", maxsplit=1)[0]
        second = path_names[1].split(":", maxsplit=1)[0]
        connection_rows.append([
            connection_label(user),
            name,
            format_value(IDEAL_CONNECTION_MBPS),
            format_stat((row.get(f"connection_{user}_goodput_mbps") for row in rows), "Mbps"),
            f"{first}: {format_stat((row.get(f'connection_{user}_{first}_mbps') for row in rows), 'Mbps')}",
            f"{second}: {format_stat((row.get(f'connection_{user}_{second}_mbps') for row in rows), 'Mbps')}",
        ])

    class_rows = [
        ["Blue x1 (X)", format_value(IDEAL_BLUE_X1_TOTAL_MBPS), format_stat((row.get("blue_x1_mbps") for row in rows), "Mbps")],
        ["Blue x2 (T)", format_value(IDEAL_BLUE_X2_TOTAL_MBPS), format_stat((row.get("blue_x2_mbps") for row in rows), "Mbps")],
        ["Red y1 (X then T)", format_value(IDEAL_RED_Y1_TOTAL_MBPS), format_stat((row.get("red_y1_mbps") for row in rows), "Mbps")],
        ["Red y2 (T)", format_value(IDEAL_RED_Y2_TOTAL_MBPS), format_stat((row.get("red_y2_mbps") for row in rows), "Mbps")],
    ]

    return [
        f"EXPERIMENT 3 - {label}",
        "\n".join([
            "PURPOSE AND SUBFLOW GOALS",
            "Test Pareto efficiency and traffic shifting using only multipath connections.",
            "Four Blue connections use x1 through X and x2 through T. Four Red connections use y2 through T and an inefficient y1 route through X then T.",
            "Red opens y2 first and y1 at 30 s. An efficient controller should leave only a one-MSS-per-RTT probe on each inefficient y1, not abandon it completely.",
            f"Reference probe: {IDEAL_PROBE_PER_CONNECTION_MBPS:.3f} Mbps per Red y1, {IDEAL_TOTAL_PROBE_MBPS:.3f} Mbps total.",
            f"Ideal aggregate goodput: {IDEAL_AGGREGATE_MBPS:.3f} Mbps; equal connection share: {IDEAL_CONNECTION_MBPS:.3f} Mbps.",
            f"Ideal per-connection paths: Blue x1 {IDEAL_BLUE_X1_TOTAL_MBPS / USERS_PER_TYPE:.3f}, Blue x2 {IDEAL_BLUE_X2_TOTAL_MBPS / USERS_PER_TYPE:.3f}, Red y1 {IDEAL_RED_Y1_TOTAL_MBPS / USERS_PER_TYPE:.3f}, Red y2 {IDEAL_RED_Y2_TOTAL_MBPS / USERS_PER_TYPE:.3f} Mbps.",
        ]),
        "\n".join([
            "MEASUREMENT",
            f"All means use {analysis_start:g} s to each run's end, well after Red y1 joins at 30 s.",
            "Connection values are application goodput; subflow values are receiver-side TCP throughput vectors.",
            "X load counts Blue x1 plus Red y1. T load counts Blue x2, Red y1, and Red y2 because y1 consumes both bottlenecks.",
        ]),
        "PER-RUN OUTCOMES (Mbps)\n" + text_table(
            ["Run", "Blue total", "Red total", "Aggregate", "Red y1", "X load", "T load"],
            run_rows,
        ),
        "CONNECTION AND SUBFLOW OUTCOMES\n" + text_table(
            ["Conn", "Type", "Conn target", "Conn achieved", "First subflow", "Second subflow"],
            connection_rows,
        ),
        "SUBFLOW-CLASS TOTALS\n" + text_table(["Class", "Target", "Achieved"], class_rows),
        "\n".join([
            "PROTOCOL MEAN",
            f"Blue total: {format_stat((row.get('blue_total_goodput_mbps') for row in rows), 'Mbps')}",
            f"Red total: {format_stat((row.get('red_total_goodput_mbps') for row in rows), 'Mbps')}",
            f"Aggregate: {format_stat((row.get('aggregate_goodput_mbps') for row in rows), 'Mbps')}",
            f"Red y1 excess above probe target: {format_stat((row.get('red_y1_excess_mbps') for row in rows), 'Mbps')}",
            f"X queue: {format_stat((row.get('x_queue_packets') for row in rows), 'packets')}",
            f"T queue: {format_stat((row.get('t_queue_packets') for row in rows), 'packets')}",
        ]),
    ]


def main() -> int:
    args = parse_args()
    sim_root = Path(__file__).resolve().parents[2]
    csv_root = sim_root / "experiments" / "experiment3" / "csvs"
    out_dir = sim_root / "plots" / "experiment3" / "summaries"
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
            row = build_run_summary(bundle, args.analysis_start)
            if not row:
                incomplete.append(f"{label} run{run}")
                continue
            add_connection_metrics(row, bundle, args.analysis_start)
            rows.append(row)

    if not rows:
        print(f"no complete experiment 3 outcomes found under {csv_root}")
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
            protocol_report(label, group, args.analysis_start),
        )
        overview_rows.append([
            label,
            len(group),
            format_stat((row.get("blue_total_goodput_mbps") for row in group), "Mbps"),
            format_stat((row.get("red_total_goodput_mbps") for row in group), "Mbps"),
            format_stat((row.get("aggregate_goodput_mbps") for row in group), "Mbps"),
            format_stat((row.get("red_y1_mbps") for row in group), "Mbps"),
        ])

    sections = [
        "EXPERIMENT 3 OUTCOME OVERVIEW",
        f"Discovered run IDs: {', '.join(map(str, runs))}",
        text_table(["Protocol", "Runs", "Blue total", "Red total", "Aggregate", "Red y1"], overview_rows),
    ]
    if incomplete:
        sections.append("INCOMPLETE DATA\n" + "\n".join(f"- {item}" for item in incomplete))
    sections.append("Detailed per-run and aggregate values are in run_metrics.csv and aggregate_metrics.csv.")
    write_text(out_dir / "overview.txt", sections)
    print(f"wrote experiment 3 outcome summaries under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

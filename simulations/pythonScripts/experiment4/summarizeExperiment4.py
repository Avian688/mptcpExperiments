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

from plotExperiment4 import (
    BACKGROUND_FLOW_COUNT,
    BASELINE_START,
    COMPETITION_END,
    COMPETITION_START,
    CONTESTED_START,
    FINAL_WINDOW_SECONDS,
    PATH_CAPACITY_MBPS,
    PROTOCOLS,
    RECOVERY_FRACTION,
    SUSTAIN_SECONDS,
    aggregate_summary,
    build_run_summary,
    load_bundle,
    mean_value,
    series_end,
)


FAIR_CONTESTED_PATH2_MBPS = PATH_CAPACITY_MBPS / (BACKGROUND_FLOW_COUNT + 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize experiment 4 CSV outcomes.")
    parser.add_argument("--runs", nargs="*", type=int, help="Run IDs to include; default discovers all available runs.")
    return parser.parse_args()


def add_phase_metrics(row: dict[str, object], bundle) -> None:
    end = series_end(bundle)
    final_start = max(COMPETITION_END, end - FINAL_WINDOW_SECONDS)
    row["analysis_end_time_s"] = end
    row["final_window_start_time_s"] = final_start
    for name, series in (("path1", bundle.path1), ("path2", bundle.path2)):
        row[f"{name}_baseline_mbps"] = mean_value(
            series, BASELINE_START, COMPETITION_START, 1e6
        )
        row[f"{name}_contested_mbps"] = mean_value(
            series, CONTESTED_START, COMPETITION_END, 1e6
        )
        row[f"{name}_final_mbps"] = mean_value(series, final_start, end, 1e6)

    row["main_goodput_baseline_mbps"] = mean_value(
        bundle.goodput, BASELINE_START, COMPETITION_START, 1e6
    )
    row["main_goodput_contested_mbps"] = mean_value(
        bundle.goodput, CONTESTED_START, COMPETITION_END, 1e6
    )
    row["main_goodput_final_mbps"] = mean_value(bundle.goodput, final_start, end, 1e6)
    for index, series in enumerate(bundle.background_goodput, start=1):
        row[f"background_{index}_contested_mbps"] = mean_value(
            series, CONTESTED_START, COMPETITION_END, 1e6
        )
    for path_name, queue in bundle.queues.items():
        key = path_name.lower().replace(" ", "")
        row[f"{key}_queue_baseline_packets"] = mean_value(
            queue, BASELINE_START, COMPETITION_START
        )
        row[f"{key}_queue_final_packets"] = mean_value(queue, final_start, end)


def protocol_report(label: str, rows: list[dict[str, object]]) -> list[str]:
    run_rows = [
        [
            row["run"],
            format_value(row.get("main_goodput_baseline_mbps")),
            format_value(row.get("main_goodput_contested_mbps")),
            format_value(row.get("main_goodput_final_mbps")),
            format_value(row.get("path2_contested_mbps")),
            format_value(row.get("throughput_recovery_time_s")),
            format_value(row.get("throughput_recovery_deficit_mbit")),
        ]
        for row in sorted(rows, key=lambda item: int(item["run"]))
    ]

    phase_rows = []
    for path in ("path1", "path2"):
        phase_rows.append([
            path.title().replace("Path", "Path "),
            format_stat((row.get(f"{path}_baseline_mbps") for row in rows), "Mbps"),
            format_stat((row.get(f"{path}_contested_mbps") for row in rows), "Mbps"),
            format_stat((row.get(f"{path}_final_mbps") for row in rows), "Mbps"),
        ])
    phase_rows.append([
        "Main app",
        format_stat((row.get("main_goodput_baseline_mbps") for row in rows), "Mbps"),
        format_stat((row.get("main_goodput_contested_mbps") for row in rows), "Mbps"),
        format_stat((row.get("main_goodput_final_mbps") for row in rows), "Mbps"),
    ])

    background_rows = [
        [
            f"Background {index}",
            format_value(FAIR_CONTESTED_PATH2_MBPS),
            format_stat((row.get(f"background_{index}_contested_mbps") for row in rows), "Mbps"),
        ]
        for index in range(1, BACKGROUND_FLOW_COUNT + 1)
    ]

    queue_rows = [
        [
            path,
            format_stat((row.get(f"{key}_queue_baseline_packets") for row in rows), "packets"),
            format_stat((row.get(f"{key}_queue_contested_packets") for row in rows), "packets"),
            format_stat((row.get(f"{key}_queue_final_packets") for row in rows), "packets"),
        ]
        for path, key in (("Path 1", "path1"), ("Path 2", "path2"))
    ]

    return [
        f"EXPERIMENT 4 - {label}",
        "\n".join([
            "PURPOSE AND SUBFLOW GOALS",
            "Test responsiveness when one subflow's path suddenly becomes contested and later clears.",
            f"The main MPTCP connection has two 20 Mbps, 20 ms paths. Five one-subflow connections join Path 2 at {COMPETITION_START:g} s and stop at {COMPETITION_END:g} s.",
            "Path 1 goal: remain close to 20 Mbps throughout. Path 2 goal: start near 20 Mbps, yield under competition, then recover near 20 Mbps quickly and without a large recovery deficit.",
            "Main application goal: start and finish near 40 Mbps while shifting traffic promptly enough to limit the contested-period reduction.",
            f"An uncoupled equal-flow reference during competition is {FAIR_CONTESTED_PATH2_MBPS:.2f} Mbps for the main Path 2 subflow and each background connection; it is a reference, not a hard target for coupled MPTCP.",
        ]),
        "\n".join([
            "MEASUREMENT WINDOWS",
            f"Baseline: {BASELINE_START:g}-{COMPETITION_START:g} s.",
            f"Contested steady state: {CONTESTED_START:g}-{COMPETITION_END:g} s, excluding the initial response transient.",
            f"Final: the last {FINAL_WINDOW_SECONDS:g} s after competition ends.",
            "Main-connection values are application goodput; path values are receiver-side TCP throughput vectors.",
            f"Recovery requires at least {RECOVERY_FRACTION * 100:.0f}% of baseline sustained for {SUSTAIN_SECONDS:g} s after {COMPETITION_END:g} s.",
        ]),
        "PER-RUN OUTCOMES (rates in Mbps)\n" + text_table(
            ["Run", "App base", "App contested", "App final", "Path 2 contested", "Recovery s", "Deficit Mbit"],
            run_rows,
        ),
        "PHASE MEANS\n" + text_table(["Series", "Baseline", "Contested", "Final"], phase_rows),
        "BACKGROUND FLOW OUTCOMES\n" + text_table(["Flow", "Fair reference", "Achieved"], background_rows),
        "QUEUE OCCUPANCY\n" + text_table(["Queue", "Baseline", "Contested", "Final"], queue_rows),
        "\n".join([
            "PROTOCOL MEAN",
            f"Final main goodput: {format_stat((row.get('main_goodput_final_mbps') for row in rows), 'Mbps')}",
            f"Path 2 throughput recovery: {format_stat((row.get('throughput_recovery_time_s') for row in rows), 's')}",
            f"Path 2 recovery deficit: {format_stat((row.get('throughput_recovery_deficit_mbit') for row in rows), 'Mbit')}",
            f"Throughput recovery success fraction: {format_stat((row.get('throughput_recovery_success') for row in rows), digits=2)}",
        ]),
    ]


def main() -> int:
    args = parse_args()
    sim_root = Path(__file__).resolve().parents[2]
    csv_root = sim_root / "experiments" / "experiment4" / "csvs"
    out_dir = sim_root / "plots" / "experiment4" / "summaries"
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
            row = build_run_summary(bundle)
            add_phase_metrics(row, bundle)
            rows.append(row)

    if not rows:
        print(f"no complete experiment 4 outcomes found under {csv_root}")
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
        write_text(out_dir / report_filename(protocol), protocol_report(label, group))
        overview_rows.append([
            label,
            len(group),
            format_stat((row.get("main_goodput_contested_mbps") for row in group), "Mbps"),
            format_stat((row.get("main_goodput_final_mbps") for row in group), "Mbps"),
            format_stat((row.get("throughput_recovery_time_s") for row in group), "s"),
            format_stat((row.get("throughput_recovery_deficit_mbit") for row in group), "Mbit"),
        ])

    sections = [
        "EXPERIMENT 4 OUTCOME OVERVIEW",
        f"Discovered run IDs: {', '.join(map(str, runs))}",
        text_table(["Protocol", "Runs", "Contested app", "Final app", "Recovery", "Deficit"], overview_rows),
    ]
    if incomplete:
        sections.append("INCOMPLETE DATA\n" + "\n".join(f"- {item}" for item in incomplete))
    sections.append("Detailed per-run and aggregate values are in run_metrics.csv and aggregate_metrics.csv.")
    write_text(out_dir / "overview.txt", sections)
    print(f"wrote experiment 4 outcome summaries under {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

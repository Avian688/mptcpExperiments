#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from plotHelpers import annotated_heatmap, mean_std_annotations, save_figure

MSS_BYTES = 1448
PATH_CAPACITY_MBPS = 20.0
COMPETITION_START = 40.0
COMPETITION_END = 80.0
BASELINE_START = 20.0
CONTESTED_START = 60.0
FINAL_WINDOW_SECONDS = 60.0
RECOVERY_FRACTION = 0.9
SUSTAIN_SECONDS = 5.0
SAMPLE_SECONDS = 0.5
DEFAULT_RUNS = [1, 2, 3, 4, 5]
BACKGROUND_FLOW_COUNT = 5
QUEUE_MODULES = {
    "Path 1": "baliaresponsiveness.p1Ingress.ppp[0].queue",
    "Path 2": "baliaresponsiveness.p2Ingress.ppp[0].queue",
}

PROTOCOLS = [
    ("lia", "LIA"),
    ("olia", "OLIA"),
    ("balia", "BALIA"),
    ("mporb", "MPORB Uncoupled"),
    ("mporb_alpha", "MPORB Alpha"),
    ("mporb_delta", "MPORB Delta"),
    ("mporb_epsilon", "MPORB Epsilon"),
]


@dataclass
class Bundle:
    run: int
    protocol: str
    label: str
    goodput: pd.Series
    path1: pd.Series
    path2: pd.Series
    cwnd1: pd.Series
    cwnd2: pd.Series
    background_goodput: list[pd.Series]
    queues: dict[str, pd.Series]


def read_series(path: Path, column: str) -> pd.Series | None:
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    if "time" not in frame.columns or column not in frame.columns:
        return None
    series = pd.Series(frame[column].to_numpy(dtype=float), index=frame["time"].to_numpy(dtype=float))
    return series[~series.index.duplicated(keep="last")].sort_index()


def conn_id(path: Path) -> int:
    match = re.search(r"\.conn-(\d+)$", path.parent.name)
    return int(match.group(1)) if match else -1


def resample(series: pd.Series, grid: np.ndarray) -> pd.Series:
    if series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    return series.reindex(series.index.union(grid)).sort_index().ffill().reindex(grid).fillna(0)


def load_connection_series(
    run_root: Path, module_prefix: str, metric: str, count: int | None = None
) -> list[pd.Series]:
    paths = sorted(
        (
            path
            for path in run_root.glob(f"*/{metric}.csv")
            if path.parent.name.startswith(module_prefix)
        ),
        key=conn_id,
    )
    series = [item for path in paths if (item := read_series(path, metric)) is not None and not item.empty]
    return series[-count:] if count is not None else series


def path2_index(paths: list[pd.Series]) -> int:
    contested_grid = np.arange(CONTESTED_START, COMPETITION_END, SAMPLE_SECONDS)
    means = [float(resample(path, contested_grid).mean()) for path in paths]
    return int(np.argmin(means))


def load_bundle(csv_root: Path, protocol: str, label: str, run: int) -> Bundle | None:
    run_root = csv_root / protocol / f"run{run}"
    goodput = read_series(
        run_root / "baliaresponsiveness.server[0].app[0]" / "goodput.csv", "goodput"
    )
    throughput = load_connection_series(
        run_root, "baliaresponsiveness.server[0].tcp.conn-", "throughput", 2
    )
    congestion_windows = load_connection_series(
        run_root, "baliaresponsiveness.client[0].tcp.conn-", "cwnd", 2
    )
    background_goodput = [
        item
        for path in sorted(run_root.glob("*/goodput.csv"))
        if path.parent.name.startswith("baliaresponsiveness.backgroundServer[")
        and (item := read_series(path, "goodput")) is not None
        and not item.empty
    ]
    queues = {
        name: read_series(run_root / module / "queueLength.csv", "queueLength")
        for name, module in QUEUE_MODULES.items()
    }

    if (
        goodput is None
        or len(throughput) != 2
        or len(congestion_windows) != 2
        or len(background_goodput) != BACKGROUND_FLOW_COUNT
        or any(queue is None for queue in queues.values())
    ):
        print(
            f"warning: incomplete {label} run{run}: goodput={goodput is not None}, "
            f"throughput subflows={len(throughput)}, cwnd subflows={len(congestion_windows)}, "
            f"background flows={len(background_goodput)}, "
            f"queues={sum(queue is not None for queue in queues.values())}/{len(QUEUE_MODULES)}"
        )
        return None

    contested_grid = np.arange(CONTESTED_START, COMPETITION_END, SAMPLE_SECONDS)
    inactive_background = [
        index
        for index, series in enumerate(background_goodput)
        if float(resample(series, contested_grid).mean()) <= 0.0
    ]
    if inactive_background:
        print(
            f"warning: invalid {label} run{run}: no contested-window delivery from "
            f"background flow(s) {inactive_background}"
        )
        return None

    suppressed = path2_index(throughput)
    other = 1 - suppressed
    return Bundle(
        run,
        protocol,
        label,
        goodput,
        throughput[other],
        throughput[suppressed],
        congestion_windows[other],
        congestion_windows[suppressed],
        background_goodput,
        {name: queue for name, queue in queues.items() if queue is not None},
    )


def series_end(bundle: Bundle) -> float:
    return max(
        float(series.index.max())
        for series in (
            bundle.goodput,
            bundle.path1,
            bundle.path2,
            bundle.cwnd1,
            bundle.cwnd2,
            *bundle.queues.values(),
        )
    )


def mean_value(series: pd.Series, start: float, end: float, divisor: float = 1.0) -> float:
    grid = np.arange(start, end, SAMPLE_SECONDS)
    if grid.size == 0:
        return np.nan
    return float(resample(series, grid).mean() / divisor)


def background_values(bundle: Bundle, grid: np.ndarray) -> np.ndarray:
    values = np.zeros_like(grid, dtype=float)
    for series in bundle.background_goodput:
        values += resample(series, grid).to_numpy(dtype=float)
    values[(grid < COMPETITION_START) | (grid >= COMPETITION_END)] = 0.0
    return values


def recovery_metrics(
    series: pd.Series, baseline: float, start: float, end: float, divisor: float
) -> tuple[float, int, float]:
    grid = np.arange(start, end + SAMPLE_SECONDS, SAMPLE_SECONDS)
    values = resample(series, grid) / divisor
    threshold = RECOVERY_FRACTION * baseline
    sustain_samples = max(1, int(round(SUSTAIN_SECONDS / SAMPLE_SECONDS)))
    sustained = values.rolling(window=sustain_samples, min_periods=sustain_samples).mean()
    recovered = sustained[sustained >= threshold]
    recovery_time = float(recovered.index[0] - start) if not recovered.empty else np.nan

    deficit_end = float(recovered.index[0]) if not recovered.empty else end
    deficit_grid = grid[grid <= deficit_end]
    deficit_values = values.reindex(deficit_grid).to_numpy(dtype=float)
    deficit = float(np.trapezoid(np.maximum(baseline - deficit_values, 0.0), deficit_grid))
    return recovery_time, int(not recovered.empty), deficit


def build_run_summary(bundle: Bundle) -> dict[str, float | int | str]:
    end = series_end(bundle)
    final_start = max(COMPETITION_END, end - FINAL_WINDOW_SECONDS)
    cwnd_baseline = mean_value(bundle.cwnd2, BASELINE_START, COMPETITION_START, MSS_BYTES)
    rate_baseline = mean_value(bundle.path2, BASELINE_START, COMPETITION_START, 1e6)
    cwnd_recovery, cwnd_success, cwnd_deficit = recovery_metrics(
        bundle.cwnd2, cwnd_baseline, COMPETITION_END, end, MSS_BYTES
    )
    rate_recovery, rate_success, rate_deficit = recovery_metrics(
        bundle.path2, rate_baseline, COMPETITION_END, end, 1e6
    )
    contested_grid = np.arange(CONTESTED_START, COMPETITION_END, SAMPLE_SECONDS)

    return {
        "run": bundle.run,
        "protocol": bundle.protocol,
        "label": bundle.label,
        "path2_baseline_mbps": rate_baseline,
        "path2_contested_mbps": mean_value(bundle.path2, CONTESTED_START, COMPETITION_END, 1e6),
        "path2_final_mbps": mean_value(bundle.path2, final_start, end, 1e6),
        "path2_cwnd_baseline_packets": cwnd_baseline,
        "path2_cwnd_contested_packets": mean_value(
            bundle.cwnd2, CONTESTED_START, COMPETITION_END, MSS_BYTES
        ),
        "path2_cwnd_final_packets": mean_value(bundle.cwnd2, final_start, end, MSS_BYTES),
        "background_contested_mbps": float(background_values(bundle, contested_grid).mean() / 1e6),
        "final_goodput_mbps": mean_value(bundle.goodput, final_start, end, 1e6),
        "path1_queue_contested_packets": mean_value(
            bundle.queues["Path 1"], CONTESTED_START, COMPETITION_END
        ),
        "path2_queue_contested_packets": mean_value(
            bundle.queues["Path 2"], CONTESTED_START, COMPETITION_END
        ),
        "cwnd_recovery_time_s": cwnd_recovery,
        "cwnd_recovery_success": cwnd_success,
        "cwnd_recovery_deficit_packet_seconds": cwnd_deficit,
        "throughput_recovery_time_s": rate_recovery,
        "throughput_recovery_success": rate_success,
        "throughput_recovery_deficit_mbit": rate_deficit,
    }


def aggregate_summary(run_summary: pd.DataFrame) -> pd.DataFrame:
    numeric = [
        column
        for column in run_summary.select_dtypes(include=[np.number]).columns
        if column != "run"
    ]
    rows = []
    for (protocol, label), group in run_summary.groupby(["protocol", "label"], sort=False):
        row: dict[str, float | int | str] = {
            "protocol": protocol,
            "label": label,
            "run_count": int(group["run"].nunique()),
        }
        for column in numeric:
            values = group[column].dropna().astype(float)
            row[column] = float(values.mean()) if not values.empty else np.nan
            row[f"{column}_std"] = float(values.std(ddof=0)) if not values.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def band(
    ax, grid: np.ndarray, series: list[pd.Series], label: str, divisor: float = 1e6
) -> None:
    matrix = np.vstack(
        [resample(item, grid).to_numpy(dtype=float) / divisor for item in series]
    )
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    ax.plot(grid, mean, label=label)
    ax.fill_between(grid, np.maximum(mean - std, 0), mean + std, alpha=0.18)


def mark_competition(ax) -> None:
    ax.axvspan(COMPETITION_START, COMPETITION_END, color="grey", alpha=0.12)
    ax.axvline(COMPETITION_START, color="grey", linestyle=":", linewidth=1)
    ax.axvline(COMPETITION_END, color="grey", linestyle=":", linewidth=1)
    ax.set_xlabel("Time (s)")
    ax.grid(True, alpha=0.3)


def save_goodput_small_multiples(
    grouped: dict[str, list[Bundle]],
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    bundles = [bundle for group in grouped.values() for bundle in group]
    if not bundles:
        return
    end = max(series_end(bundle) for bundle in bundles)
    grid = np.arange(BASELINE_START, end + SAMPLE_SECONDS, SAMPLE_SECONDS)
    fig, axes = plt.subplots(2, 3, figsize=(13.0, 7.2), sharex=True, sharey=True)
    for ax, (protocol, label) in zip(axes.flat, PROTOCOLS):
        group = grouped.get(protocol, [])
        if group:
            band(ax, grid, [bundle.goodput for bundle in group], label)
        ax.axhline(
            2 * PATH_CAPACITY_MBPS,
            color="black",
            linestyle="--",
            linewidth=1,
        )
        ax.set_title(label)
        mark_competition(ax)
    for ax in axes[:, 0]:
        ax.set_ylabel("Goodput (Mbps)")
    fig.suptitle("Main Connection Goodput")
    save_figure(fig, out_dir / "goodput.pdf", combined_pdf)


def save_phase_heatmap(
    summary: pd.DataFrame,
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    columns = ["path2_baseline_mbps", "path2_contested_mbps", "path2_final_mbps"]
    means = summary[columns].to_numpy(dtype=float)
    deviations = summary[[f"{column}_std" for column in columns]].to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    annotated_heatmap(
        ax,
        means,
        summary["label"].tolist(),
        ["Before", "During", "After"],
        "Path 2 throughput (Mbps)",
        annotations=mean_std_annotations(means, deviations, decimals=2),
        cmap="viridis",
    )
    ax.set_title("Path 2 Response")
    ax.set_xlabel("Competition phase")
    save_figure(fig, out_dir / "path2_response.pdf", combined_pdf)


def save_responsiveness_plot(
    run_summary: pd.DataFrame,
    summary: pd.DataFrame,
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    labels = summary["label"].tolist()
    positions = np.arange(len(labels))
    fig, axes = plt.subplots(1, 2, figsize=(12.0, 5.2), sharey=True)
    tick_labels = []

    for position, (protocol, label) in enumerate(zip(summary["protocol"], labels)):
        runs = run_summary[run_summary["protocol"] == protocol]
        recovery_times = runs["throughput_recovery_time_s"].dropna().to_numpy(dtype=float)
        deficits = runs["throughput_recovery_deficit_mbit"].dropna().to_numpy(dtype=float)
        tick_labels.append(f"{label} ({len(recovery_times)}/{len(runs)})")

        if len(recovery_times):
            jitter = np.linspace(-0.1, 0.1, len(recovery_times))
            axes[0].scatter(recovery_times, position + jitter, s=20, alpha=0.45)
            axes[0].errorbar(
                float(np.mean(recovery_times)),
                position,
                xerr=float(np.std(recovery_times)),
                fmt="D",
                color="black",
                capsize=3,
            )
        if len(deficits):
            jitter = np.linspace(-0.1, 0.1, len(deficits))
            axes[1].scatter(deficits, position + jitter, s=20, alpha=0.45)
            axes[1].errorbar(
                float(np.mean(deficits)),
                position,
                xerr=float(np.std(deficits)),
                fmt="D",
                color="black",
                capsize=3,
            )

    axes[0].set_title("Recovery Time")
    axes[0].set_xlabel("Seconds after competition")
    axes[1].set_title("Recovery Deficit")
    axes[1].set_xlabel("Mbit")
    axes[0].set_yticks(positions, tick_labels)
    axes[0].invert_yaxis()
    for ax in axes:
        ax.grid(True, axis="x", alpha=0.3)
    fig.suptitle("Responsiveness (recovered runs / total)")
    save_figure(fig, out_dir / "responsiveness.pdf", combined_pdf)


def save_queue_heatmap(
    summary: pd.DataFrame,
    out_dir: Path,
    combined_pdf: PdfPages,
) -> None:
    columns = ["path1_queue_contested_packets", "path2_queue_contested_packets"]
    means = summary[columns].to_numpy(dtype=float)
    deviations = summary[[f"{column}_std" for column in columns]].to_numpy(dtype=float)
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    annotated_heatmap(
        ax,
        means,
        summary["label"].tolist(),
        ["Path 1", "Path 2"],
        "Queue occupancy (packets)",
        annotations=mean_std_annotations(means, deviations, decimals=1),
        cmap="magma",
    )
    ax.set_title("Queues During Competition")
    save_figure(fig, out_dir / "queues.pdf", combined_pdf)


def individual_output_dir(bundle: Bundle, out_root: Path) -> Path:
    out_dir = out_root / "individual" / bundle.protocol / f"run{bundle.run}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def individual_grid(bundle: Bundle) -> np.ndarray:
    return np.arange(BASELINE_START, series_end(bundle) + SAMPLE_SECONDS, SAMPLE_SECONDS)


def save_individual_goodput_plot(
    bundle: Bundle,
    grid: np.ndarray,
    out_dir: Path,
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(10.0, 7.0), sharex=True)
    axes[0].plot(grid, resample(bundle.goodput, grid) / 1e6, label="Main connection")
    axes[0].axhline(
        2 * PATH_CAPACITY_MBPS,
        color="black",
        linestyle="--",
        linewidth=1,
        label="Total capacity",
    )
    axes[0].set_title("Aggregate goodput")
    axes[0].set_ylabel("Mbps")
    axes[0].legend()

    axes[1].plot(grid, resample(bundle.path1, grid) / 1e6, label="Path 1")
    axes[1].plot(grid, resample(bundle.path2, grid) / 1e6, label="Path 2")
    axes[1].plot(
        grid,
        background_values(bundle, grid) / 1e6,
        linestyle="--",
        label="Competing flows",
    )
    axes[1].axhline(
        PATH_CAPACITY_MBPS,
        color="black",
        linestyle="--",
        linewidth=1,
        label="Path capacity",
    )
    axes[1].set_title("Path throughput")
    axes[1].set_ylabel("Mbps")
    axes[1].legend(ncol=4, fontsize=8)
    for ax in axes:
        mark_competition(ax)
    fig.suptitle(f"{bundle.label}, Run {bundle.run}")
    save_figure(fig, out_dir / "goodput.pdf")


def save_individual_cwnd_plot(
    bundle: Bundle,
    grid: np.ndarray,
    out_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    ax.step(
        grid,
        resample(bundle.cwnd1, grid) / MSS_BYTES,
        where="post",
        label="Path 1",
    )
    ax.step(
        grid,
        resample(bundle.cwnd2, grid) / MSS_BYTES,
        where="post",
        label="Path 2",
    )
    ax.set_title(f"{bundle.label}, Run {bundle.run}")
    ax.set_ylabel("cwnd (packets)")
    ax.legend()
    mark_competition(ax)
    save_figure(fig, out_dir / "cwnd.pdf")


def save_individual_queue_plot(
    bundle: Bundle,
    grid: np.ndarray,
    out_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    for name in ("Path 1", "Path 2"):
        ax.step(
            grid,
            resample(bundle.queues[name], grid),
            where="post",
            label=name,
        )
    ax.set_title(f"{bundle.label}, Run {bundle.run}")
    ax.set_ylabel("Queue occupancy (packets)")
    ax.legend()
    mark_competition(ax)
    save_figure(fig, out_dir / "queues.pdf")


def save_individual_plots(bundle: Bundle, out_root: Path) -> None:
    grid = individual_grid(bundle)
    if len(grid) == 0:
        return
    out_dir = individual_output_dir(bundle, out_root)
    save_individual_goodput_plot(bundle, grid, out_dir)
    save_individual_cwnd_plot(bundle, grid, out_dir)
    save_individual_queue_plot(bundle, grid, out_dir)


def selected_runs(args: argparse.Namespace) -> list[int]:
    if args.run is not None:
        return [args.run]
    return sorted(set(args.runs)) if args.runs else DEFAULT_RUNS


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot mptcpExperiments experiment 4.")
    parser.add_argument("--run", type=int)
    parser.add_argument("--runs", nargs="*", type=int)
    args = parser.parse_args()

    sim_root = Path(__file__).resolve().parents[2]
    csv_root = sim_root / "experiments" / "experiment4" / "csvs"
    out_dir = sim_root / "plots" / "experiment4"
    shutil.rmtree(out_dir, ignore_errors=True)
    aggregate_dir = out_dir / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)

    bundles = [
        bundle
        for run in selected_runs(args)
        for protocol, label in PROTOCOLS
        if (bundle := load_bundle(csv_root, protocol, label, run)) is not None
    ]
    if not bundles:
        print(f"no extracted CSV data found under {csv_root}")
        return 1

    run_summary = pd.DataFrame(build_run_summary(bundle) for bundle in bundles)
    summary = aggregate_summary(run_summary)
    run_summary.to_csv(out_dir / "summary_runs.csv", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False)

    grouped: dict[str, list[Bundle]] = defaultdict(list)
    for bundle in bundles:
        grouped[bundle.protocol].append(bundle)
    with PdfPages(out_dir / "aggregate.pdf") as combined_pdf:
        save_goodput_small_multiples(grouped, aggregate_dir, combined_pdf)
        save_phase_heatmap(summary, aggregate_dir, combined_pdf)
        save_responsiveness_plot(run_summary, summary, aggregate_dir, combined_pdf)
        save_queue_heatmap(summary, aggregate_dir, combined_pdf)
    for bundle in bundles:
        save_individual_plots(bundle, out_dir)

    print(f"wrote experiment 4 plots under {out_dir}")
    print(f"wrote combined aggregate plots to {out_dir / 'aggregate.pdf'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

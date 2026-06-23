#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CONFIGS = [
    ("cubic", "default", "CUBIC default"),
    ("cubic", "lowestRtt", "CUBIC lowestRTT"),
    ("mporb", "default", "MPORB default"),
    ("mporb", "lowestRtt", "MPORB lowestRTT"),
]

NETWORK = "schedulernegativetwopaths"
MSS_BYTES = 1448
DEFAULT_RUNS = [1, 2, 3, 4, 5]


@dataclass
class SeriesBundle:
    run: int
    protocol: str
    scheduler: str
    label: str
    variant: str
    variable_rtt_ms: int | None
    app_goodput: pd.Series
    subflows: list[pd.Series]
    hol_blocked: pd.Series | None
    dsn_gap: pd.Series | None
    reinjected_bytes: pd.Series | None
    reinjections: pd.Series | None


def parse_variant_rtt_ms(variant: str) -> int | None:
    match = re.fullmatch(r"(?:rtt)?0*(\d+)ms", variant)
    return int(match.group(1)) if match else None


def read_series(path: Path, column: str) -> pd.Series | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    if "time" not in df.columns or column not in df.columns:
        return None
    series = pd.Series(df[column].to_numpy(dtype=float), index=df["time"].to_numpy(dtype=float))
    return series[~series.index.duplicated(keep="last")].sort_index()


def sample_hold_to_grid(series: pd.Series | None, grid: np.ndarray) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    return series.reindex(series.index.union(grid)).sort_index().ffill().reindex(grid).fillna(0)


def connection_metric_paths(run_root: Path, metric: str, endpoint: str = "server") -> list[Path]:
    return sorted(
        path
        for path in run_root.glob(f"*/{metric}.csv")
        if f"{NETWORK}.{endpoint}[0].tcp.conn" in path.parent.name
    )


def read_connection_series(run_root: Path, metric: str, endpoint: str = "server") -> pd.Series | None:
    candidates = [
        series
        for path in connection_metric_paths(run_root, metric, endpoint)
        if (series := read_series(path, metric)) is not None and not series.empty
    ]
    return max(candidates, key=len) if candidates else None


def run_root_for(csv_root: Path, protocol: str, scheduler: str, variant: str, run: int) -> Path:
    variant_root = csv_root / protocol / scheduler / variant / f"run{run}"
    if variant_root.exists():
        return variant_root
    return csv_root / protocol / scheduler / f"run{run}"


def load_bundle(csv_root: Path, protocol: str, scheduler: str, label: str, variant: str, run: int) -> SeriesBundle | None:
    run_root = run_root_for(csv_root, protocol, scheduler, variant, run)
    app_path = run_root / f"{NETWORK}.server[0].app[0]" / "goodput.csv"
    app_goodput = read_series(app_path, "goodput")
    if app_goodput is None:
        print(f"warning: missing app goodput for {label} {variant} run{run}: {app_path}")
        return None

    subflows = [
        series
        for path in connection_metric_paths(run_root, "throughput")
        if (series := read_series(path, "throughput")) is not None
    ]
    subflows = sorted(subflows, key=lambda s: float(s.mean()) if not s.empty else 0.0, reverse=True)[:2]

    return SeriesBundle(
        run=run,
        protocol=protocol,
        scheduler=scheduler,
        label=label,
        variant=variant,
        variable_rtt_ms=parse_variant_rtt_ms(variant),
        app_goodput=app_goodput,
        subflows=subflows,
        hol_blocked=read_connection_series(run_root, "holBlockedBytes"),
        dsn_gap=read_connection_series(run_root, "metaDsnGapBytes"),
        reinjected_bytes=read_connection_series(run_root, "metaReinjectedBytes", "client"),
        reinjections=read_connection_series(run_root, "metaReinjections", "client"),
    )


def discover_variants(csv_root: Path, runs: list[int]) -> list[str]:
    variants: set[str] = set()
    for protocol, scheduler, _label in CONFIGS:
        root = csv_root / protocol / scheduler
        if not root.exists():
            continue
        for child in root.iterdir():
            if child.is_dir() and any((child / f"run{run}").is_dir() for run in runs):
                variants.add(child.name)
        if any((root / f"run{run}").is_dir() for run in runs):
            variants.add("single")
    return sorted(variants, key=lambda item: (parse_variant_rtt_ms(item) is None, parse_variant_rtt_ms(item) or 0, item))


def common_grid(bundles: list[SeriesBundle]) -> np.ndarray:
    starts = []
    ends = []
    for bundle in bundles:
        all_series = [
            bundle.app_goodput,
            *bundle.subflows,
            bundle.hol_blocked,
            bundle.dsn_gap,
            bundle.reinjected_bytes,
            bundle.reinjections,
        ]
        starts.extend(float(series.index.min()) for series in all_series if series is not None and not series.empty)
        ends.extend(float(series.index.max()) for series in all_series if series is not None and not series.empty)
    if not starts or not ends:
        return np.asarray([])
    return np.arange(max(min(starts), 0.0), max(ends) + 0.5, 0.5)


def aggregate_subflows(bundle: SeriesBundle, grid: np.ndarray) -> pd.Series:
    total = pd.Series(np.zeros_like(grid), index=grid)
    for series in bundle.subflows:
        total = total.add(sample_hold_to_grid(series, grid), fill_value=0)
    return total


def window_mean(series: pd.Series, start_time: float) -> float:
    window = series[series.index >= start_time]
    if window.empty:
        window = series
    return float(window.mean()) if not window.empty else 0.0


def p95(series: pd.Series) -> float:
    return float(series.quantile(0.95)) if not series.empty else 0.0


def last_positive_time(series: pd.Series) -> float | None:
    positive = series[series > 0]
    return float(positive.index.max()) if not positive.empty else None


def bytes_to_packets(series: pd.Series) -> pd.Series:
    return series / MSS_BYTES


def series_stats(series_list: list[pd.Series | None], grid: np.ndarray) -> tuple[pd.Series, pd.Series]:
    sampled = [sample_hold_to_grid(series, grid).to_numpy(dtype=float) for series in series_list if series is not None]
    if not sampled:
        zeros = pd.Series(np.zeros_like(grid), index=grid)
        return zeros, zeros
    matrix = np.vstack(sampled)
    return pd.Series(matrix.mean(axis=0), index=grid), pd.Series(matrix.std(axis=0), index=grid)


def summarize_bundle(
    bundle: SeriesBundle,
    final_window: float,
    analysis_start: float,
) -> dict[str, float | int | str | None]:
    grid = common_grid([bundle])
    if len(grid) == 0:
        return {}

    final_window_start = max(float(grid.max()) - final_window, float(grid.min()))
    app = sample_hold_to_grid(bundle.app_goodput, grid)
    last_delivery_time = last_positive_time(app)
    subflow_total = aggregate_subflows(bundle, grid)
    hol_gap = (subflow_total - app).clip(lower=0)
    hol = bytes_to_packets(sample_hold_to_grid(bundle.hol_blocked, grid))
    dsn_gap = bytes_to_packets(sample_hold_to_grid(bundle.dsn_gap, grid))
    reinjected = bytes_to_packets(sample_hold_to_grid(bundle.reinjected_bytes, grid))
    reinjections = sample_hold_to_grid(bundle.reinjections, grid)

    row: dict[str, float | int | str | None] = {
        "variant": bundle.variant,
        "variable_rtt_ms": bundle.variable_rtt_ms,
        "run": bundle.run,
        "protocol": bundle.protocol,
        "scheduler": bundle.scheduler,
        "label": bundle.label,
        "analysis_start_time_s": analysis_start,
        "analysis_end_time_s": float(grid.max()),
        "final_window_start_time_s": final_window_start,
        "app_goodput_mbps": window_mean(app / 1e6, final_window_start),
        "run_average_app_goodput_mbps": window_mean(app / 1e6, analysis_start),
        "last_positive_app_goodput_time_s": last_delivery_time,
        "app_delivery_stall_duration_s": (
            max(float(grid.max()) - last_delivery_time, 0.0) if last_delivery_time is not None else None
        ),
        "subflow_sum_mbps": window_mean(subflow_total / 1e6, final_window_start),
        "hol_gap_mbps": window_mean(hol_gap / 1e6, final_window_start),
        "hol_blocked_packets": window_mean(hol, final_window_start),
        "dsn_gap_packets": window_mean(dsn_gap, final_window_start),
        "max_hol_blocked_packets": float(hol.max()) if not hol.empty else 0.0,
        "p95_hol_blocked_packets": p95(hol),
        "hol_blocked_fraction": float((hol > 0).mean()) if not hol.empty else 0.0,
        "max_dsn_gap_packets": float(dsn_gap.max()) if not dsn_gap.empty else 0.0,
        "p95_dsn_gap_packets": p95(dsn_gap),
        "meta_reinjected_packets": float(reinjected.iloc[-1]) if not reinjected.empty else 0.0,
        "meta_reinjections": float(reinjections.iloc[-1]) if not reinjections.empty else 0.0,
    }
    for index, series in enumerate(bundle.subflows, start=1):
        row[f"subflow_{index}_mbps"] = window_mean(sample_hold_to_grid(series, grid) / 1e6, final_window_start)
    return row


def aggregate_summary(run_summary: pd.DataFrame) -> pd.DataFrame:
    key_cols = ["variant", "variable_rtt_ms", "protocol", "scheduler", "label"]
    numeric_cols = [
        column
        for column in run_summary.select_dtypes(include=[np.number]).columns
        if column not in {"run", "variable_rtt_ms"}
    ]
    rows = []
    for keys, group in run_summary.groupby(key_cols, dropna=False, sort=False):
        row = dict(zip(key_cols, keys))
        row["run_count"] = int(group["run"].nunique())
        for column in numeric_cols:
            values = group[column].dropna().astype(float)
            row[column] = float(values.mean()) if not values.empty else np.nan
            row[f"{column}_std"] = float(values.std(ddof=0)) if not values.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["variable_rtt_ms", "protocol", "scheduler"], na_position="last")


def grouped_by_config(bundles: list[SeriesBundle]) -> list[tuple[str, list[SeriesBundle]]]:
    grouped: dict[str, list[SeriesBundle]] = defaultdict(list)
    for bundle in bundles:
        grouped[bundle.label].append(bundle)
    return [(label, grouped[label]) for _protocol, _scheduler, label in CONFIGS if label in grouped]


def save_variant_goodput_plot(variant: str, bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    plt.figure(figsize=(10, 5))
    for label, group in grouped_by_config(bundles):
        mean, std = series_stats([bundle.app_goodput for bundle in group], grid)
        mean_mbps = mean / 1e6
        std_mbps = std / 1e6
        plt.plot(grid, mean_mbps, label=f"{label} (n={len(group)})")
        plt.fill_between(grid, mean_mbps - std_mbps, mean_mbps + std_mbps, alpha=0.18)
    plt.xlabel("Time (s)")
    plt.ylabel("Application goodput (Mbps)")
    plt.title(f"Application Goodput, {variant}")
    plt.grid(True, alpha=0.3)
    plt.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "aggregate_goodput_timeseries.pdf")
    plt.close()


def save_variant_subflow_plot(variant: str, bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    groups = grouped_by_config(bundles)
    rows = int(np.ceil(len(groups) / 2))
    fig, axes = plt.subplots(rows, 2, figsize=(11, max(4, rows * 2.8)), sharex=True, sharey=True)
    axes = np.asarray(axes).reshape(rows, 2)
    for ax, (label, group) in zip(axes.flat, groups):
        max_subflows = max((len(bundle.subflows) for bundle in group), default=0)
        for index in range(max_subflows):
            mean, std = series_stats(
                [bundle.subflows[index] if index < len(bundle.subflows) else None for bundle in group],
                grid,
            )
            mean_mbps = mean / 1e6
            std_mbps = std / 1e6
            ax.plot(grid, mean_mbps, label=f"subflow {index + 1}")
            ax.fill_between(grid, mean_mbps - std_mbps, mean_mbps + std_mbps, alpha=0.16)
        ax.set_title(f"{label} (n={len(group)})")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    for ax in axes.flat[len(groups):]:
        ax.axis("off")
    for ax in axes[-1, :]:
        ax.set_xlabel("Time (s)")
    for ax in axes[:, 0]:
        ax.set_ylabel("Subflow throughput (Mbps)")
    fig.suptitle(f"Per-Subflow Goodput Proxy, {variant}")
    fig.tight_layout()
    fig.savefig(out_dir / "per_subflow_goodput_timeseries.pdf")
    plt.close(fig)


def save_variant_hol_plot(variant: str, bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    for label, group in grouped_by_config(bundles):
        hol_mean, hol_std = series_stats(
            [bytes_to_packets(sample_hold_to_grid(bundle.hol_blocked, grid)) for bundle in group],
            grid,
        )
        dsn_mean, dsn_std = series_stats(
            [bytes_to_packets(sample_hold_to_grid(bundle.dsn_gap, grid)) for bundle in group],
            grid,
        )
        reinj_mean, reinj_std = series_stats([bundle.reinjections for bundle in group], grid)
        for ax, mean, std, y_label in (
            (axes[0], hol_mean, hol_std, "HoL blocked (MSS packets)"),
            (axes[1], dsn_mean, dsn_std, "DSN gap (MSS packets)"),
            (axes[2], reinj_mean, reinj_std, "Meta reinjections"),
        ):
            ax.plot(grid, mean, label=f"{label} (n={len(group)})")
            ax.fill_between(grid, mean - std, mean + std, alpha=0.16)
            ax.set_ylabel(y_label)
    axes[0].set_title(f"Receiver HoL, {variant}")
    axes[2].set_xlabel("Time (s)")
    for ax in axes:
        ax.grid(True, alpha=0.3)
        ax.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "hol_and_dsn_gap_timeseries.pdf")
    plt.close(fig)


def save_variant_plots(
    variant: str,
    bundles: list[SeriesBundle],
    out_root: Path,
    final_window: float,
    analysis_start: float,
) -> list[dict[str, float | int | str | None]]:
    out_dir = out_root / "by_rtt" / variant
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = common_grid(bundles)
    if len(grid) == 0:
        return []

    save_variant_goodput_plot(variant, bundles, grid, out_dir)
    save_variant_subflow_plot(variant, bundles, grid, out_dir)
    save_variant_hol_plot(variant, bundles, grid, out_dir)

    rows = [summarize_bundle(bundle, final_window, analysis_start) for bundle in bundles]
    rows = [row for row in rows if row]
    pd.DataFrame(rows).to_csv(out_dir / "summary_runs_final_window.csv", index=False)
    aggregate_summary(pd.DataFrame(rows)).to_csv(out_dir / "summary_final_window.csv", index=False)
    return rows


def plot_summary_lines(summary: pd.DataFrame, metric: str, ylabel: str, title: str, out_path: Path) -> None:
    data = summary.dropna(subset=["variable_rtt_ms"])
    if data.empty:
        return
    plt.figure(figsize=(10, 5))
    for protocol, scheduler, label in CONFIGS:
        subset = data[(data["protocol"] == protocol) & (data["scheduler"] == scheduler)].sort_values("variable_rtt_ms")
        if subset.empty:
            continue
        yerr = subset[f"{metric}_std"] if f"{metric}_std" in subset.columns else None
        plt.errorbar(
            subset["variable_rtt_ms"],
            subset[metric],
            yerr=yerr,
            marker="o",
            capsize=3,
            linewidth=1.2,
            elinewidth=0.9,
            label=label,
        )
    plt.xlabel("Variable path RTT (ms)")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def save_aggregate_plots(run_summary: pd.DataFrame, summary: pd.DataFrame, out_dir: Path) -> None:
    aggregate_dir = out_dir / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    run_summary.to_csv(aggregate_dir / "summary_runs_by_rtt.csv", index=False)
    summary.to_csv(aggregate_dir / "summary_by_rtt.csv", index=False)
    run_summary.to_csv(out_dir / "summary_runs_final_window.csv", index=False)
    summary.to_csv(out_dir / "summary_final_window.csv", index=False)

    plot_summary_lines(
        summary,
        "app_goodput_mbps",
        "Final-window app goodput (Mbps)",
        "Application Goodput vs Variable Path RTT",
        aggregate_dir / "goodput_vs_rtt.pdf",
    )
    plot_summary_lines(
        summary,
        "run_average_app_goodput_mbps",
        "Post-join app goodput (Mbps)",
        "Post-Join Application Goodput vs Variable Path RTT",
        aggregate_dir / "run_average_goodput_vs_rtt.pdf",
    )
    plot_summary_lines(
        summary,
        "last_positive_app_goodput_time_s",
        "Last positive app-goodput sample (s)",
        "Application Delivery Cutoff vs Variable Path RTT",
        aggregate_dir / "app_delivery_cutoff_vs_rtt.pdf",
    )
    plot_summary_lines(
        summary,
        "max_hol_blocked_packets",
        "Max HoL-blocked data (MSS packets)",
        "Peak Receiver HoL vs Variable Path RTT",
        aggregate_dir / "max_hol_blocked_vs_rtt.pdf",
    )
    plot_summary_lines(
        summary,
        "p95_hol_blocked_packets",
        "P95 HoL-blocked data (MSS packets)",
        "P95 Receiver HoL vs Variable Path RTT",
        aggregate_dir / "p95_hol_blocked_vs_rtt.pdf",
    )
    plot_summary_lines(
        summary,
        "hol_blocked_fraction",
        "Fraction of sampled time with HoL",
        "HoL Time Fraction vs Variable Path RTT",
        aggregate_dir / "hol_fraction_vs_rtt.pdf",
    )
    plot_summary_lines(
        summary,
        "max_dsn_gap_packets",
        "Max DSN gap (MSS packets)",
        "Peak DSN Gap vs Variable Path RTT",
        aggregate_dir / "max_dsn_gap_vs_rtt.pdf",
    )
    plot_summary_lines(
        summary,
        "meta_reinjections",
        "Cumulative meta reinjections",
        "MPTCP Meta Reinjections vs Variable Path RTT",
        aggregate_dir / "meta_reinjections_vs_rtt.pdf",
    )


def selected_runs(args: argparse.Namespace) -> list[int]:
    if args.run is not None:
        return [args.run]
    if args.runs:
        return sorted(set(args.runs))
    return DEFAULT_RUNS


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot mptcpExperiments experiment 1.")
    parser.add_argument("--run", type=int, help="Plot one run only.")
    parser.add_argument("--runs", nargs="*", type=int, help="Runs to aggregate; default is 1 2 3 4 5.")
    parser.add_argument("--final-window", type=float, default=60.0)
    parser.add_argument(
        "--analysis-start",
        type=float,
        default=10.0,
        help="Start time for post-join run averages. Defaults to 10s, after the 0-5s random join window.",
    )
    args = parser.parse_args()
    runs = selected_runs(args)

    sim_root = Path(__file__).resolve().parents[2]
    experiment_root = sim_root / "experiments" / "experiment1"
    csv_root = experiment_root / "csvs"
    out_dir = sim_root / "plots" / "experiment1"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    variants = discover_variants(csv_root, runs)
    if not variants:
        print(f"no extracted CSV data found under {csv_root}")
        return 1

    summary_rows: list[dict[str, float | int | str | None]] = []
    for variant in variants:
        bundles = [
            bundle
            for run in runs
            for protocol, scheduler, label in CONFIGS
            if (bundle := load_bundle(csv_root, protocol, scheduler, label, variant, run)) is not None
        ]
        if not bundles:
            continue
        summary_rows.extend(save_variant_plots(variant, bundles, out_dir, args.final_window, args.analysis_start))

    if not summary_rows:
        print(f"no usable timeseries data found under {csv_root}")
        return 1

    run_summary = pd.DataFrame(summary_rows)
    summary = aggregate_summary(run_summary)
    save_aggregate_plots(run_summary, summary, out_dir)
    print(f"wrote aggregate plots under {out_dir / 'aggregate'}")
    print(f"wrote per-RTT plots under {out_dir / 'by_rtt'}")
    print(f"aggregated runs: {', '.join(str(run) for run in runs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

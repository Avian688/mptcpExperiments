#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

CONFIGS = [
    ("cubic", "default", "CUBIC default"),
    ("cubic", "lowestRtt", "CUBIC lowestRTT"),
    ("cubic", "directPull", "CUBIC directPull"),
    ("mporb", "default", "MPORB default"),
    ("mporb", "lowestRtt", "MPORB lowestRTT"),
    ("mporb", "directPull", "MPORB directPull"),
]

NETWORK = "schedulernegativetwopaths"


@dataclass
class SeriesBundle:
    protocol: str
    scheduler: str
    label: str
    variant: str
    variable_rtt_ms: int | None
    app_goodput: pd.Series
    subflows: list[pd.Series]
    hol_blocked: pd.Series | None
    dsn_gap: pd.Series | None


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


def resample_to_grid(series: pd.Series | None, grid: np.ndarray) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    return series.reindex(series.index.union(grid)).interpolate(method="index").reindex(grid).fillna(0)


def sample_hold_to_grid(series: pd.Series | None, grid: np.ndarray) -> pd.Series:
    if series is None or series.empty:
        return pd.Series(np.zeros_like(grid), index=grid)
    return series.reindex(series.index.union(grid)).sort_index().ffill().reindex(grid).fillna(0)


def connection_metric_paths(run_root: Path, metric: str) -> list[Path]:
    return sorted(
        path
        for path in run_root.glob(f"*/{metric}.csv")
        if f"{NETWORK}.server[0].tcp.conn" in path.parent.name
    )


def read_connection_series(run_root: Path, metric: str) -> pd.Series | None:
    candidates = [
        series
        for path in connection_metric_paths(run_root, metric)
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
        print(f"warning: missing app goodput for {label} {variant}: {app_path}")
        return None

    subflows = [
        series
        for path in connection_metric_paths(run_root, "throughput")
        if (series := read_series(path, "throughput")) is not None
    ]
    subflows = sorted(subflows, key=lambda s: float(s.mean()) if not s.empty else 0.0, reverse=True)[:2]

    return SeriesBundle(
        protocol=protocol,
        scheduler=scheduler,
        label=label,
        variant=variant,
        variable_rtt_ms=parse_variant_rtt_ms(variant),
        app_goodput=app_goodput,
        subflows=subflows,
        hol_blocked=read_connection_series(run_root, "holBlockedBytes"),
        dsn_gap=read_connection_series(run_root, "metaDsnGapBytes"),
    )


def discover_variants(csv_root: Path, run: int) -> list[str]:
    variants: set[str] = set()
    for protocol, scheduler, _label in CONFIGS:
        root = csv_root / protocol / scheduler
        if not root.exists():
            continue
        for child in root.iterdir():
            if child.is_dir() and (child / f"run{run}").is_dir():
                variants.add(child.name)
        if (root / f"run{run}").is_dir():
            variants.add("single")
    return sorted(variants, key=lambda item: (parse_variant_rtt_ms(item) is None, parse_variant_rtt_ms(item) or 0, item))


def common_grid(bundles: list[SeriesBundle]) -> np.ndarray:
    starts = []
    ends = []
    for bundle in bundles:
        all_series = [bundle.app_goodput, *bundle.subflows, bundle.hol_blocked, bundle.dsn_gap]
        starts.extend(float(series.index.min()) for series in all_series if series is not None and not series.empty)
        ends.extend(float(series.index.max()) for series in all_series if series is not None and not series.empty)
    if not starts or not ends:
        return np.asarray([])
    return np.arange(max(min(starts), 0.0), max(ends) + 0.5, 0.5)


def aggregate_subflows(bundle: SeriesBundle, grid: np.ndarray) -> pd.Series:
    total = pd.Series(np.zeros_like(grid), index=grid)
    for series in bundle.subflows:
        total = total.add(resample_to_grid(series, grid), fill_value=0)
    return total


def window_mean(series: pd.Series, start_time: float) -> float:
    window = series[series.index >= start_time]
    if window.empty:
        window = series
    return float(window.mean()) if not window.empty else 0.0


def p95(series: pd.Series) -> float:
    return float(series.quantile(0.95)) if not series.empty else 0.0


def summarize_bundle(bundle: SeriesBundle, grid: np.ndarray, final_window: float) -> dict[str, float | int | str | None]:
    window_start = max(float(grid.max()) - final_window, float(grid.min())) if len(grid) else 0.0
    app = resample_to_grid(bundle.app_goodput, grid)
    subflow_total = aggregate_subflows(bundle, grid)
    hol_gap = (subflow_total - app).clip(lower=0)
    hol = sample_hold_to_grid(bundle.hol_blocked, grid) / 1024
    dsn_gap = sample_hold_to_grid(bundle.dsn_gap, grid) / 1024

    row: dict[str, float | int | str | None] = {
        "variant": bundle.variant,
        "variable_rtt_ms": bundle.variable_rtt_ms,
        "protocol": bundle.protocol,
        "scheduler": bundle.scheduler,
        "label": bundle.label,
        "app_goodput_mbps": window_mean(app / 1e6, window_start),
        "subflow_sum_mbps": window_mean(subflow_total / 1e6, window_start),
        "hol_gap_mbps": window_mean(hol_gap / 1e6, window_start),
        "hol_blocked_kib": window_mean(hol, window_start),
        "dsn_gap_kib": window_mean(dsn_gap, window_start),
        "max_hol_blocked_kib": float(hol.max()) if not hol.empty else 0.0,
        "p95_hol_blocked_kib": p95(hol),
        "hol_blocked_fraction": float((hol > 0).mean()) if not hol.empty else 0.0,
        "max_dsn_gap_kib": float(dsn_gap.max()) if not dsn_gap.empty else 0.0,
        "p95_dsn_gap_kib": p95(dsn_gap),
    }
    for index, series in enumerate(bundle.subflows, start=1):
        row[f"subflow_{index}_mbps"] = window_mean(resample_to_grid(series, grid) / 1e6, window_start)
    return row


def save_variant_goodput_plot(variant: str, bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    plt.figure(figsize=(10, 5))
    for bundle in bundles:
        plt.plot(grid, resample_to_grid(bundle.app_goodput, grid) / 1e6, label=bundle.label)
    plt.xlabel("Time (s)")
    plt.ylabel("Application goodput (Mbps)")
    plt.title(f"Application Goodput, {variant}")
    plt.grid(True, alpha=0.3)
    plt.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    plt.savefig(out_dir / "aggregate_goodput_timeseries.pdf")
    plt.close()


def save_variant_subflow_plot(variant: str, bundles: list[SeriesBundle], grid: np.ndarray, out_dir: Path) -> None:
    rows = int(np.ceil(len(bundles) / 2))
    fig, axes = plt.subplots(rows, 2, figsize=(11, max(4, rows * 2.8)), sharex=True, sharey=True)
    axes = np.asarray(axes).reshape(rows, 2)
    for ax, bundle in zip(axes.flat, bundles):
        for index, series in enumerate(bundle.subflows, start=1):
            ax.plot(grid, resample_to_grid(series, grid) / 1e6, label=f"subflow {index}")
        ax.set_title(bundle.label)
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    for ax in axes.flat[len(bundles):]:
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
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for bundle in bundles:
        axes[0].plot(grid, sample_hold_to_grid(bundle.hol_blocked, grid) / 1024, label=bundle.label)
        axes[1].plot(grid, sample_hold_to_grid(bundle.dsn_gap, grid) / 1024, label=bundle.label)
    axes[0].set_ylabel("HoL blocked (KiB)")
    axes[0].set_title(f"Receiver HoL, {variant}")
    axes[1].set_ylabel("DSN gap (KiB)")
    axes[1].set_xlabel("Time (s)")
    for ax in axes:
        ax.grid(True, alpha=0.3)
        ax.legend(ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "hol_and_dsn_gap_timeseries.pdf")
    plt.close(fig)


def save_variant_plots(variant: str, bundles: list[SeriesBundle], out_root: Path, final_window: float) -> list[dict[str, float | int | str | None]]:
    out_dir = out_root / "by_rtt" / variant
    out_dir.mkdir(parents=True, exist_ok=True)
    grid = common_grid(bundles)
    if len(grid) == 0:
        return []

    save_variant_goodput_plot(variant, bundles, grid, out_dir)
    save_variant_subflow_plot(variant, bundles, grid, out_dir)
    save_variant_hol_plot(variant, bundles, grid, out_dir)

    rows = [summarize_bundle(bundle, grid, final_window) for bundle in bundles]
    pd.DataFrame(rows).to_csv(out_dir / "summary_final_window.csv", index=False)
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
        plt.plot(subset["variable_rtt_ms"], subset[metric], marker="o", label=label)
    plt.xlabel("Variable path RTT (ms)")
    plt.ylabel(ylabel)
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.legend(ncol=2, fontsize=8)
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def save_aggregate_plots(summary: pd.DataFrame, out_dir: Path) -> None:
    aggregate_dir = out_dir / "aggregate"
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(aggregate_dir / "summary_by_rtt.csv", index=False)
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
        "max_hol_blocked_kib",
        "Max HoL-blocked data (KiB)",
        "Peak Receiver HoL vs Variable Path RTT",
        aggregate_dir / "max_hol_blocked_vs_rtt.pdf",
    )
    plot_summary_lines(
        summary,
        "p95_hol_blocked_kib",
        "P95 HoL-blocked data (KiB)",
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
        "max_dsn_gap_kib",
        "Max DSN gap (KiB)",
        "Peak DSN Gap vs Variable Path RTT",
        aggregate_dir / "max_dsn_gap_vs_rtt.pdf",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot mptcpExperiments experiment 1.")
    parser.add_argument("--run", type=int, default=1)
    parser.add_argument("--final-window", type=float, default=60.0)
    args = parser.parse_args()

    sim_root = Path(__file__).resolve().parents[2]
    experiment_root = sim_root / "experiments" / "experiment1"
    csv_root = experiment_root / "csvs"
    out_dir = sim_root / "plots" / "experiment1"
    out_dir.mkdir(parents=True, exist_ok=True)

    variants = discover_variants(csv_root, args.run)
    if not variants:
        print(f"no extracted CSV data found under {csv_root}")
        return 1

    summary_rows: list[dict[str, float | int | str | None]] = []
    for variant in variants:
        bundles = [
            bundle
            for protocol, scheduler, label in CONFIGS
            if (bundle := load_bundle(csv_root, protocol, scheduler, label, variant, args.run)) is not None
        ]
        if not bundles:
            continue
        summary_rows.extend(save_variant_plots(variant, bundles, out_dir, args.final_window))

    if not summary_rows:
        print(f"no usable timeseries data found under {csv_root}")
        return 1

    summary = pd.DataFrame(summary_rows)
    save_aggregate_plots(summary, out_dir)
    print(f"wrote aggregate plots under {out_dir / 'aggregate'}")
    print(f"wrote per-RTT plots under {out_dir / 'by_rtt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

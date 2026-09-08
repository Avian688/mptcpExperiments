#!/usr/bin/env python3
"""City-pair / path-count heatmaps, matched-run gains, and run variability."""

import argparse
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np

from generateExperimentMpOrbKShortestPathsIni import (
    EXPERIMENT_DIR, SIMULATIONS_DIR, MANIFEST_FILE, PAIR_DEFINITIONS, RUN_COUNT,
)
from extractSingleCsvFile import write_csv

CSV_DIR = EXPERIMENT_DIR / "csvs"
PLOT_DIR = SIMULATIONS_DIR / "plots" / "experimentMpOrbKShortestPaths"


def load_summaries(configs):
    rows = []
    for config in configs:
        path = CSV_DIR / "extracted" / config["config"] / "summary.json"
        if not path.is_file():
            continue
        row = json.loads(path.read_text())
        if any(row.get(key) != value for key, value in config.items()):
            raise ValueError(f"Stale extracted summary: {path}; rerun extraction")
        raw = CSV_DIR / "raw" / f'{config["config"]}.csv'
        if not raw.is_file() or row.get("raw_stat") != [raw.stat().st_size, raw.stat().st_mtime_ns]:
            raise ValueError(f"Missing or changed source export for {path}; rerun extraction")
        rows.append(row)
    if not rows:
        raise FileNotFoundError("No extracted results. Run steps 1-3 first.")
    return rows


def aggregate(rows, metric, ks):
    means = np.full((len(PAIR_DEFINITIONS), len(ks)), np.nan)
    deviations = means.copy()
    counts = np.zeros(means.shape, dtype=int)
    baseline = {(r["pair"], r["run"]): r for r in rows if r["k"] == 1}
    records = []
    for i, (pair, *_rest) in enumerate(PAIR_DEFINITIONS):
        for j, k in enumerate(ks):
            values = []
            for r in rows:
                if r["pair"] != pair or r["k"] != k:
                    continue
                if metric == "goodput_gain":
                    b = baseline.get((pair, r["run"]))
                    if b is None or b["seed"] != r["seed"] or b["measurement_start"] != r["measurement_start"] or b["measurement_end"] != r["measurement_end"]:
                        continue
                    value = r["goodput_mbps"] / b["goodput_mbps"] if b["goodput_mbps"] > 0 else math.nan
                else:
                    value = r[metric]
                if math.isfinite(value):
                    values.append(value)
            n = len(values)
            counts[i, j] = n
            if n:
                means[i, j] = np.mean(values)
            if n > 1:
                deviations[i, j] = np.std(values, ddof=1)
            records.append(dict(pair=pair, k=k, metric=metric, mean=means[i, j],
                                std=deviations[i, j], n=n, expected_n=RUN_COUNT))
    return means, deviations, counts, records


def pair_labels():
    return [f"{source} → {destination}" for _, source, destination, *_ in PAIR_DEFINITIONS]


def save_figure(fig, name):
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "pdf"):
        fig.savefig(PLOT_DIR / f"{name}.{suffix}", dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_heatmap(rows, metric, title, unit, ks, cmap_name="viridis", limits=None):
    means, deviations, counts, records = aggregate(rows, metric, ks)
    fig, ax = plt.subplots(figsize=(10.8, 5.4), layout="constrained")
    cmap = plt.get_cmap(cmap_name).copy()
    cmap.set_bad("#eeeeee")
    kwargs = {}
    if metric == "goodput_gain":
        valid = means[np.isfinite(means)]
        spread = max(0.2, float(np.max(np.abs(valid - 1))) if len(valid) else 0.2)
        kwargs["norm"] = TwoSlopeNorm(vmin=1 - spread, vcenter=1, vmax=1 + spread)
    elif limits:
        kwargs.update(vmin=limits[0], vmax=limits[1])
    im = ax.imshow(np.ma.masked_invalid(means), cmap=cmap, aspect="auto", **kwargs)
    for i in range(means.shape[0]):
        for j in range(means.shape[1]):
            mean, sd, n = means[i, j], deviations[i, j], counts[i, j]
            if n:
                label = f"{mean:.2f}" + (f" ± {sd:.2f}" if n > 1 else "") + f"\n(n={n}/{RUN_COUNT})"
                rgba = im.cmap(im.norm(mean))
                luminance = sum(a * b for a, b in zip(rgba[:3], (0.2126, 0.7152, 0.0722)))
                color = "black" if luminance > 0.5 else "white"
            else:
                label, color = "—\n(n=0/5)", "#555555"
            ax.text(j, i, label, ha="center", va="center", color=color, fontsize=8.5)
    ax.set_xticks(range(len(ks)), ["OrbCC\nK=1" if k == 1 else f"Alpha\nK={k}" for k in ks])
    ax.set_yticks(range(len(PAIR_DEFINITIONS)), pair_labels())
    ax.set_title(title + "\nEdge-disjoint core paths; mean ± sample SD across matched seeds", fontsize=12, pad=12)
    fig.colorbar(im, ax=ax, label=unit, shrink=0.83)
    save_figure(fig, metric)
    return records


def plot_goodput_lines(rows):
    ks = [1, 2, 3, 4, 5]
    means, deviations, counts, _ = aggregate(rows, "goodput_mbps", ks)
    fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
    for i, label in enumerate(pair_labels()):
        ax.errorbar(ks, means[i], yerr=np.where(counts[i] > 1, deviations[i], 0),
                    marker="o", capsize=3, label=label)
    ax.set_xticks(ks, ["OrbCC\nK=1", "Alpha\nK=2", "Alpha\nK=3", "Alpha\nK=4", "Alpha\nK=5"])
    ax.set_ylabel("Receiver application goodput (Mbps)")
    ax.set_title("Goodput versus requested path count · error bars: sample SD")
    ax.set_ylim(bottom=0)
    ax.grid(alpha=0.2)
    ax.legend(fontsize=9)
    save_figure(fig, "goodput_vs_path_count")


def plot_timeseries(rows):
    for pair, source, destination, *_ in PAIR_DEFINITIONS:
        fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout="constrained")
        plotted = False
        for k in range(1, 6):
            series = []
            times = None
            for row in rows:
                if row["pair"] != pair or row["k"] != k:
                    continue
                path = CSV_DIR / "extracted" / row["config"] / "timeseries.csv"
                data = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
                if times is not None and not np.array_equal(times, data[:, 0]):
                    raise ValueError(f"Mismatched time windows: {path}")
                times = data[:, 0]
                series.append(data[:, 1:])
            if not series:
                continue
            plotted = True
            values = np.stack(series)
            mean = np.mean(values, axis=0)
            label = ("OrbCC K=1" if k == 1 else f"Alpha K={k}") + f" (n={len(series)})"
            line, = axes[0].plot(times, mean[:, 0], label=label, linewidth=1.2)
            if len(series) > 1:
                sd = np.std(values[:, :, 0], axis=0, ddof=1)
                axes[0].fill_between(times, np.maximum(0, mean[:, 0] - sd), mean[:, 0] + sd,
                                     color=line.get_color(), alpha=0.12)
            axes[1].step(times, mean[:, 1], where="post", color=line.get_color())
        if not plotted:
            plt.close(fig)
            continue
        axes[0].set_title(f"{source} → {destination} · goodput and catalog availability")
        axes[0].set_ylabel("Application goodput (Mbps)")
        axes[0].set_ylim(bottom=0)
        axes[0].legend(ncol=3, fontsize=8)
        axes[1].set_ylabel("Available selected ranks")
        axes[1].set_xlabel("Simulation time (s)")
        axes[1].set_yticks(range(6))
        axes[1].set_ylim(-0.1, 5.1)
        for ax in axes:
            ax.grid(alpha=0.2)
        save_figure(fig, f"timeseries_{pair}")


def plot_results(configs, timeseries=True):
    rows = load_summaries(configs)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    records = []
    specs = (
        ("goodput_mbps", "Receiver application goodput", "Mbps", [1, 2, 3, 4, 5], "viridis", (0, 100)),
        ("goodput_gain", "Alpha goodput / OrbCC on the same rank-1 catalog path", "Ratio (1 = baseline)", [2, 3, 4, 5], "RdYlGn", None),
        ("all_k_available_pct", "Time with all K requested ranks present in the catalog", "% of measurement window", [1, 2, 3, 4, 5], "viridis", (0, 100)),
        ("highest_rank_rtt_ms", "Propagation RTT of the highest selected rank, when available", "ms", [1, 2, 3, 4, 5], "magma", None),
        ("sender_rtt_ms", "Measured TCP RTT at the sender (ACK-sample mean)", "ms", [1, 2, 3, 4, 5], "magma", None),
    )
    for spec in specs:
        records.extend(plot_heatmap(rows, *spec))
    write_csv(PLOT_DIR / "plot_data.csv", list(records[0]), records)
    plot_goodput_lines(rows)
    if timeseries:
        plot_timeseries(rows)
    print(f"Plotted {len(rows)}/{len(configs)} extracted runs in {PLOT_DIR}; missing values remain blank")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-timeseries", action="store_true")
    args = parser.parse_args()
    plot_results(json.loads(MANIFEST_FILE.read_text()), not args.no_timeseries)

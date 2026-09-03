#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
import subprocess
from pathlib import Path

from experimentKShortestPathsSupport import tool_path
from generateExperimentKShortestPathsIni import (
    PAIR_DEFINITIONS,
    EXPERIMENT_DIR,
    PATH_COUNT,
    POLICIES,
)


plt = None
np = None
PdfPages = None


def load_plot_dependencies():
    global plt, np, PdfPages
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as pyplot
        import numpy as numpy
        from matplotlib.backends.backend_pdf import PdfPages as PdfPagesClass
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Analysis requires matplotlib and numpy; use the same Python environment as the other experiment plot scripts"
        ) from error
    plt = pyplot
    np = numpy
    PdfPages = PdfPagesClass


RESULTS_DIR = EXPERIMENT_DIR / "results"
CSV_DIR = EXPERIMENT_DIR / "csvs"
PLOTS_DIR = EXPERIMENT_DIR.parents[1] / "plots" / "experimentKShortestPaths"

SOURCE_TO_PAIR = {
    source_index: (pair_key, source_city, destination_city)
    for pair_key, source_city, destination_city, source_index, _ in PAIR_DEFINITIONS
}

VECTOR_NAMES = {
    "rtt": "rtt",
    "pingTxSeq": "ping_tx",
    "kPathAvailable": "available",
    "kPathExpectedRtt": "expected_rtt",
    "kPathCoreLinkCount": "core_links",
    "kPathCatalogSize": "catalog_size",
}

POLICY_SHORT_LABELS = {
    "Unrestricted": "Any",
    "Shared5": "<=5",
    "Shared4": "<=4",
    "Shared3": "<=3",
    "Shared2": "<=2",
    "Shared1": "<=1",
    "EdgeDisjoint": "Edge",
}


def parse_values(value):
    if not value:
        return []
    return [float(item) for item in value.split()]


def find_vector_file(policy_name):
    exact = RESULTS_DIR / f"Ping_{policy_name}-#0.vec"
    if exact.is_file():
        return exact
    matches = sorted(
        RESULTS_DIR.glob(f"Ping_{policy_name}-*.vec"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not matches:
        raise FileNotFoundError(f"No vector result found for Ping_{policy_name} in {RESULTS_DIR}")
    return matches[0]


def export_policy(policy_name):
    vector_file = find_vector_file(policy_name)
    exported_file = RESULTS_DIR / f"Ping_{policy_name}.csv"
    subprocess.run(
        [
            tool_path("opp_scavetool"),
            "export",
            "-o",
            str(exported_file),
            "-F",
            "CSV-R",
            str(vector_file),
        ],
        cwd=EXPERIMENT_DIR,
        check=True,
    )
    print(f"Exported {vector_file.name}")
    return exported_file


def read_policy_vectors(policy_name, exported_file):
    module_pattern = re.compile(r"\.userTerminal\[(\d+)\]\.app\[(\d+)\]$")
    vectors = {}
    with exported_file.open(newline="", encoding="utf-8") as csv_file:
        for row in csv.DictReader(csv_file):
            if row.get("type") != "vector":
                continue
            metric_name = row.get("name", "").split(":", 1)[0]
            metric = VECTOR_NAMES.get(metric_name)
            if metric is None:
                continue
            module_match = module_pattern.search(row.get("module", ""))
            if module_match is None:
                continue
            source_index = int(module_match.group(1))
            app_index = int(module_match.group(2))
            pair = SOURCE_TO_PAIR.get(source_index)
            if pair is None or app_index >= PATH_COUNT:
                continue
            pair_key, source_city, destination_city = pair
            key = (policy_name, pair_key, app_index + 1)
            vectors.setdefault(
                key,
                {
                    "source_city": source_city,
                    "destination_city": destination_city,
                },
            )
            vectors[key][metric] = {
                "times": parse_values(row.get("vectime")),
                "values": parse_values(row.get("vecvalue")),
            }
    return vectors


def positive_milliseconds(metric):
    if not metric:
        return []
    return [value * 1000 for value in metric["values"] if np.isfinite(value) and value >= 0]


def summarize(vectors, selected_policies):
    rows = []
    rtt_samples = []
    path_samples = []

    for policy_name in selected_policies:
        for pair_key, source_city, destination_city, _, _ in PAIR_DEFINITIONS:
            for path_rank in range(1, PATH_COUNT + 1):
                data = vectors.get((policy_name, pair_key, path_rank), {})
                rtt_metric = data.get("rtt", {})
                rtt_times = rtt_metric.get("times", [])
                rtt_ms = [value * 1000 for value in rtt_metric.get("values", [])]
                tx_count = len(data.get("ping_tx", {}).get("values", []))
                available_values = data.get("available", {}).get("values", [])
                expected_rtt_ms = positive_milliseconds(data.get("expected_rtt"))
                core_links = [
                    value for value in data.get("core_links", {}).get("values", []) if value >= 0
                ]
                catalog_sizes = data.get("catalog_size", {}).get("values", [])

                rows.append(
                    {
                        "policy": policy_name,
                        "pair": pair_key,
                        "source": source_city,
                        "destination": destination_city,
                        "path_rank": path_rank,
                        "tx_count": tx_count,
                        "rx_count": len(rtt_ms),
                        "ping_success_pct": 100 * len(rtt_ms) / tx_count if tx_count else np.nan,
                        "catalog_availability_pct": 100 * np.mean(available_values) if available_values else np.nan,
                        "mean_rtt_ms": float(np.mean(rtt_ms)) if rtt_ms else np.nan,
                        "mean_expected_rtt_ms": float(np.mean(expected_rtt_ms)) if expected_rtt_ms else np.nan,
                        "mean_core_links": float(np.mean(core_links)) if core_links else np.nan,
                        "mean_catalog_size": float(np.mean(catalog_sizes)) if catalog_sizes else np.nan,
                    }
                )

                for time_value, rtt_value in zip(rtt_times, rtt_ms):
                    rtt_samples.append(
                        {
                            "policy": policy_name,
                            "pair": pair_key,
                            "path_rank": path_rank,
                            "time_s": time_value,
                            "rtt_ms": rtt_value,
                        }
                    )

                path_times = data.get("available", {}).get("times", [])
                expected_values = data.get("expected_rtt", {}).get("values", [])
                core_link_values = data.get("core_links", {}).get("values", [])
                catalog_size_values = data.get("catalog_size", {}).get("values", [])
                for sample_index, time_value in enumerate(path_times):
                    path_samples.append(
                        {
                            "policy": policy_name,
                            "pair": pair_key,
                            "path_rank": path_rank,
                            "time_s": time_value,
                            "available": available_values[sample_index] if sample_index < len(available_values) else np.nan,
                            "expected_rtt_ms": expected_values[sample_index] * 1000 if sample_index < len(expected_values) and expected_values[sample_index] >= 0 else np.nan,
                            "core_links": core_link_values[sample_index] if sample_index < len(core_link_values) and core_link_values[sample_index] >= 0 else np.nan,
                            "catalog_size": catalog_size_values[sample_index] if sample_index < len(catalog_size_values) else np.nan,
                        }
                    )

    baseline_by_pair = {
        row["pair"]: row["mean_rtt_ms"]
        for row in rows
        if row["policy"] == "Unrestricted" and row["path_rank"] == 1
    }
    for row in rows:
        baseline = baseline_by_pair.get(row["pair"], np.nan)
        row["rtt_penalty_pct"] = (
            100 * (row["mean_rtt_ms"] / baseline - 1)
            if np.isfinite(row["mean_rtt_ms"]) and np.isfinite(baseline) and baseline > 0
            else np.nan
        )
        row["rtt_model_error_ms"] = (
            row["mean_rtt_ms"] - row["mean_expected_rtt_ms"]
            if np.isfinite(row["mean_rtt_ms"]) and np.isfinite(row["mean_expected_rtt_ms"])
            else np.nan
        )
    return rows, rtt_samples, path_samples


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise RuntimeError(f"No data available for {path.name}")
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def matrix_for(rows, policies, pair_key, field):
    matrix = np.full((PATH_COUNT, len(policies)), np.nan)
    for row in rows:
        if row["pair"] != pair_key or row["policy"] not in policies:
            continue
        matrix[row["path_rank"] - 1, policies.index(row["policy"])] = row[field]
    return matrix


def aggregate_matrix(rows, policies, field):
    matrix = np.full((PATH_COUNT, len(policies)), np.nan)
    for rank in range(1, PATH_COUNT + 1):
        for policy_index, policy_name in enumerate(policies):
            values = [
                row[field]
                for row in rows
                if row["policy"] == policy_name
                and row["path_rank"] == rank
                and np.isfinite(row[field])
            ]
            if values:
                matrix[rank - 1, policy_index] = float(np.mean(values))
    return matrix


def heatmap(ax, matrix, policies, title, color_map, minimum, maximum, suffix):
    cmap = plt.get_cmap(color_map).copy()
    cmap.set_bad("#d9d9d9")
    image = ax.imshow(np.ma.masked_invalid(matrix), aspect="auto", cmap=cmap, vmin=minimum, vmax=maximum)
    ax.set_title(title)
    ax.set_xlabel("Path policy")
    ax.set_ylabel("Path rank")
    ax.set_xticks(range(len(policies)), [POLICY_SHORT_LABELS[name] for name in policies], rotation=35, ha="right")
    ax.set_yticks(range(PATH_COUNT), range(1, PATH_COUNT + 1))
    for row_index in range(matrix.shape[0]):
        for column_index in range(matrix.shape[1]):
            value = matrix[row_index, column_index]
            label = "n/a" if not np.isfinite(value) else f"{value:.0f}{suffix}"
            ax.text(column_index, row_index, label, ha="center", va="center", fontsize=7)
    plt.colorbar(image, ax=ax, fraction=0.046, pad=0.04)


def make_figure(rows, policies, pair_key=None, title=None):
    if pair_key is None:
        average_rtt = aggregate_matrix(rows, policies, "mean_rtt_ms")
        penalty = aggregate_matrix(rows, policies, "rtt_penalty_pct")
        availability = aggregate_matrix(rows, policies, "catalog_availability_pct")
    else:
        average_rtt = matrix_for(rows, policies, pair_key, "mean_rtt_ms")
        penalty = matrix_for(rows, policies, pair_key, "rtt_penalty_pct")
        availability = matrix_for(rows, policies, pair_key, "catalog_availability_pct")

    finite_rtts = average_rtt[np.isfinite(average_rtt)]
    finite_penalties = penalty[np.isfinite(penalty)]
    rtt_maximum = max(10, float(np.max(finite_rtts))) if finite_rtts.size else 10
    penalty_maximum = max(10, float(np.max(finite_penalties))) if finite_penalties.size else 10
    figure, axes = plt.subplots(1, 3, figsize=(18, 6), constrained_layout=True)
    heatmap(
        axes[0],
        average_rtt,
        policies,
        "Average RTT",
        "RdYlGn_r",
        0,
        rtt_maximum,
        " ms",
    )
    heatmap(
        axes[1],
        penalty,
        policies,
        "RTT penalty",
        "RdYlGn_r",
        0,
        penalty_maximum,
        "%",
    )
    heatmap(
        axes[2],
        availability,
        policies,
        "Path availability",
        "RdYlGn",
        0,
        100,
        "%",
    )
    figure.suptitle(title)
    figure.text(
        0.5,
        0.005,
        "RTT penalty is relative to unrestricted path 1. Gray cells have no RTT samples.",
        ha="center",
        fontsize=9,
    )
    return figure


def plot_results(rows, policies):
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    combined_path = PLOTS_DIR / "experimentKShortestPaths.pdf"
    with PdfPages(combined_path) as combined_pdf:
        aggregate = make_figure(rows, policies, title="All city pairs")
        aggregate.savefig(PLOTS_DIR / "all_pairs.png", dpi=200)
        aggregate.savefig(PLOTS_DIR / "all_pairs.pdf")
        combined_pdf.savefig(aggregate)
        plt.close(aggregate)

        for pair_key, source_city, destination_city, _, _ in PAIR_DEFINITIONS:
            figure = make_figure(
                rows,
                policies,
                pair_key=pair_key,
                title=f"{source_city} to {destination_city}",
            )
            figure.savefig(PLOTS_DIR / f"{pair_key}.png", dpi=200)
            figure.savefig(PLOTS_DIR / f"{pair_key}.pdf")
            combined_pdf.savefig(figure)
            plt.close(figure)
    print(f"Wrote plots under {PLOTS_DIR}")


def print_summary(rows, policies):
    print("\nPolicy summary across all city pairs and available ranks")
    print("policy            mean RTT penalty   path availability   ping success")
    for policy_name in policies:
        policy_rows = [row for row in rows if row["policy"] == policy_name]
        penalties = [row["rtt_penalty_pct"] for row in policy_rows if np.isfinite(row["rtt_penalty_pct"])]
        availability = [row["catalog_availability_pct"] for row in policy_rows if np.isfinite(row["catalog_availability_pct"])]
        success = [row["ping_success_pct"] for row in policy_rows if np.isfinite(row["ping_success_pct"])]
        print(
            f"{policy_name:<16}"
            f"{np.mean(penalties) if penalties else np.nan:>12.1f}%"
            f"{np.mean(availability) if availability else np.nan:>18.1f}%"
            f"{np.mean(success) if success else np.nan:>15.1f}%"
        )


def analyze(selected_policies=None, skip_export=False):
    load_plot_dependencies()
    policies = list(selected_policies or POLICIES)
    all_vectors = {}
    for policy_name in policies:
        exported_file = RESULTS_DIR / f"Ping_{policy_name}.csv"
        if not skip_export:
            exported_file = export_policy(policy_name)
        elif not exported_file.is_file():
            raise FileNotFoundError(f"Missing exported CSV for {policy_name}: {exported_file}")
        all_vectors.update(read_policy_vectors(policy_name, exported_file))

    rows, rtt_samples, path_samples = summarize(all_vectors, policies)
    write_csv(CSV_DIR / "summary.csv", rows)
    write_csv(CSV_DIR / "rtt_samples.csv", rtt_samples)
    write_csv(CSV_DIR / "path_samples.csv", path_samples)
    plot_results(rows, policies)
    print_summary(rows, policies)


def parse_args():
    parser = argparse.ArgumentParser(description="Extract and plot K-shortest-path ping results")
    parser.add_argument("--policies", nargs="+", choices=list(POLICIES), default=list(POLICIES))
    parser.add_argument("--skip-export", action="store_true", help="Use existing CSV-R exports")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    analyze(arguments.policies, arguments.skip_export)

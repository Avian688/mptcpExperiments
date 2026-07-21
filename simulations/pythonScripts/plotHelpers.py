#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

HIGH_IS_GOOD_CMAP = "RdYlGn"
LOW_IS_GOOD_CMAP = "RdYlGn_r"


def mean_std_annotations(
    means: np.ndarray,
    standard_deviations: np.ndarray | None = None,
    decimals: int = 1,
) -> np.ndarray:
    means = np.asarray(means, dtype=float)
    annotations = np.empty(means.shape, dtype=object)
    for row, column in np.ndindex(means.shape):
        mean = means[row, column]
        if not np.isfinite(mean):
            annotations[row, column] = "-"
            continue
        annotation = f"{mean:.{decimals}f}"
        if standard_deviations is not None:
            deviation = float(standard_deviations[row, column])
            if np.isfinite(deviation):
                annotation += f"\n+/- {deviation:.{decimals}f}"
        annotations[row, column] = annotation
    return annotations


def target_closeness(values: np.ndarray, targets: np.ndarray | float) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    targets = np.broadcast_to(np.asarray(targets, dtype=float), values.shape)
    scale = np.maximum(np.abs(targets), np.finfo(float).eps)
    return np.clip(1.0 - np.abs(values - targets) / scale, 0.0, 1.0)


def annotated_heatmap(
    ax,
    values: np.ndarray,
    row_labels: list[str],
    column_labels: list[str],
    colorbar_label: str,
    *,
    annotations: np.ndarray | None = None,
    color_values: np.ndarray | None = None,
    cmap: str = HIGH_IS_GOOD_CMAP,
    norm=None,
) -> None:
    values = np.asarray(values, dtype=float)
    color_values = values if color_values is None else np.asarray(color_values, dtype=float)
    if color_values.shape != values.shape:
        raise ValueError("heatmap color values must match the annotated values")
    image = ax.imshow(np.ma.masked_invalid(color_values), aspect="auto", cmap=cmap, norm=norm)
    ax.set_xticks(np.arange(len(column_labels)), column_labels)
    ax.set_yticks(np.arange(len(row_labels)), row_labels)
    ax.tick_params(axis="x", labelrotation=20)

    if annotations is None:
        annotations = mean_std_annotations(values)
    for row, column in np.ndindex(values.shape):
        value = values[row, column]
        color_value = color_values[row, column]
        if not np.isfinite(value) or not np.isfinite(color_value):
            text_color = "#333333"
        else:
            red, green, blue, _alpha = image.cmap(image.norm(color_value))
            luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
            text_color = "black" if luminance > 0.58 else "white"
        ax.text(
            column,
            row,
            annotations[row, column],
            ha="center",
            va="center",
            color=text_color,
            fontsize=8,
        )

    colorbar = ax.figure.colorbar(image, ax=ax, fraction=0.035, pad=0.03)
    colorbar.set_label(colorbar_label)


def save_figure(
    fig,
    path: Path,
    combined_pdf: PdfPages | None = None,
    *,
    tight_layout: bool = True,
) -> None:
    if tight_layout:
        fig.tight_layout()
    fig.savefig(path)
    if combined_pdf is not None:
        combined_pdf.savefig(fig)
    plt.close(fig)

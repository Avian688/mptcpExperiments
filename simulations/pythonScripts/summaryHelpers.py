#!/usr/bin/env python3

from __future__ import annotations

import csv
import math
import re
import shutil
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np


RUN_DIRECTORY = re.compile(r"run(\d+)")


def discover_runs(csv_root: Path, requested: Sequence[int] | None = None) -> list[int]:
    available = {
        int(match.group(1))
        for path in csv_root.rglob("run*")
        if path.is_dir()
        and (match := RUN_DIRECTORY.fullmatch(path.name)) is not None
        and any(path.rglob("*.csv"))
    }
    if requested:
        return sorted(set(requested) & available)
    return sorted(available)


def available_protocols(
    csv_root: Path, configured: Sequence[tuple[str, str]]
) -> list[tuple[str, str]]:
    labels = dict(configured)
    directories = (
        {path.name for path in csv_root.iterdir() if path.is_dir()}
        if csv_root.exists()
        else set()
    )
    ordered = [(protocol, label) for protocol, label in configured if protocol in directories]
    known = {protocol for protocol, _label in configured}
    ordered.extend(
        (protocol, labels.get(protocol, protocol.replace("_", " ").title()))
        for protocol in sorted(directories - known)
    )
    return ordered


def finite_values(values: Iterable[float | int | None]) -> list[float]:
    result = []
    for value in values:
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            result.append(number)
    return result


def mean_std(values: Iterable[float | int | None]) -> tuple[float, float, int]:
    usable = finite_values(values)
    if not usable:
        return math.nan, math.nan, 0
    return float(np.mean(usable)), float(np.std(usable, ddof=0)), len(usable)


def format_value(value: float | int | None, unit: str = "", digits: int = 2) -> str:
    if value is None or not math.isfinite(float(value)):
        return "N/A"
    suffix = f" {unit}" if unit else ""
    return f"{float(value):.{digits}f}{suffix}"


def format_stat(
    values: Iterable[float | int | None], unit: str = "", digits: int = 2
) -> str:
    mean, deviation, count = mean_std(values)
    if count == 0:
        return "N/A"
    suffix = f" {unit}" if unit else ""
    if count == 1:
        return f"{mean:.{digits}f}{suffix} (n=1)"
    return f"{mean:.{digits}f} +/- {deviation:.{digits}f}{suffix} (n={count})"


def text_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    cells = [[str(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in cells:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def render(row: Sequence[str]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip()

    separator = "-+-".join("-" * width for width in widths)
    return "\n".join([render(list(headers)), separator, *(render(row) for row in cells)])


def prepare_output_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, sections: Sequence[str]) -> None:
    content = "\n\n".join(section.rstrip() for section in sections if section.strip())
    path.write_text(content + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    if not rows:
        return
    columns: list[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def report_filename(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") + ".txt"

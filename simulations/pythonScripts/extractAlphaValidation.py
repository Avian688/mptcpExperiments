#!/usr/bin/env python3
"""Stream only selected vector fields; keep RAM independent of CSV/vector size."""
from pathlib import Path
import sys
from streamScaveCsv import extract_vectors
from alphaValidation import METRICS
VECTORS_TO_EXTRACT = set(METRICS)


def main(metrics=None):
    selected = VECTORS_TO_EXTRACT if metrics is None else set(metrics)
    if len(sys.argv) != 5:
        print("usage: extractAlphaValidation.py <experiment> <scavetool_csv> <case> <run>")
        return 2
    number, csv_path, case, run = sys.argv[1:]
    out_root = Path(__file__).resolve().parents[1] / 'experiments' / f'experiment{int(number)}' / 'csvs' / case / f'run{run}'
    try:
        return 0 if extract_vectors(Path(csv_path), out_root, selected) else 1
    except (OSError, ValueError) as error:
        print(f"Extraction failed: {error}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

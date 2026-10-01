#!/usr/bin/env python3
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extractAlphaValidation import main
from parkingLot import METRICS

if __name__ == '__main__':
    raise SystemExit(main(metrics=METRICS))

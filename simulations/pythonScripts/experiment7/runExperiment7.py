#!/usr/bin/env python3
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
from runAlphaValidation import main
from parkingLot import configurations, generate

if __name__ == '__main__':
    raise SystemExit(main(7, configurations=configurations(), generate_inputs=generate,
                         plot_script=SCRIPT_DIR / 'plotExperiment7.py',
                         extract_script=SCRIPT_DIR / 'extractSingleCsvFile.py'))

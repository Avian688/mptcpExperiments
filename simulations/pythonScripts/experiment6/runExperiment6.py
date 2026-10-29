from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runAlphaValidation import main
from redistributionExperiments import configurations, generate
if __name__ == '__main__':
    raise SystemExit(main(6, configurations=configurations(6), generate_inputs=generate,
        plot_script=Path(__file__).with_name('plotExperiment6.py'),
        extract_script=Path(__file__).with_name('extractSingleCsvFile.py')))

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
from leoExperiments import generate
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sim-time", type=float, default=300)
    args = parser.parse_args()
    generate(9, args.sim_time)

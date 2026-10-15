#!/usr/bin/env python3
"""Stream only selected vector fields; keep RAM independent of CSV/vector size."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streamScaveCsv import extract_vectors
VECTORS_TO_EXTRACT = {
    "additiveIncrease",
    "U",
    "goodput",
    "throughput",
    "cwnd",
    "cwndLimited",
    "lossRecovery",
    "numRtos",
    "retransmissionRate",
    "liaAlpha",
    "oliaEpsilon",
    "baliaAi",
    "baliaMd",
    "semiCoupledAlphaSubflowRate",
    "semiCoupledAlphaConnectionRate",
    "semiCoupledAlphaRateShare",
    "mpOrbOliaBestPath",
    "mpOrbOliaMaxWindowPath",
    "mpOrbOliaCorrection",
    "mpOrbOliaPathPrice",
    "mpOrbOliaPathOpportunity",
    "mpOrbOliaNormalizedWindow",
    "mpOrbBetaRelaxation",
    "mpOrbBetaWeight",
    "mpOrbBetaWeightCorrection",
    "mpOrbBetaSmoothedU",
    "mpOrbBetaUtilizationError",
    "mpOrbBetaRateShare",
    "mpOrbBetaBaselineShare",
    "mpOrbBetaRedistributionActive",
    "mpOrbBetaWeightedAi",
    "mpOrbBetaAlphaAi",
    "mpOrbBetaUncoupledAi",
    "semiCoupledBetaFairRate",
    "semiCoupledBetaTotalFairRate",
    "semiCoupledBetaFairRateShare",
    "holBlockedBytes",
    "subflowSendQueueBytes",
    "metaReinjectedBytes",
    "metaReinjections",
    "queueLength",
}


def main():
    selected = VECTORS_TO_EXTRACT
    if len(sys.argv) != 4:
        print("usage: extractSingleCsvFile.py <scavetool_csv> <protocol> <run>")
        return 2
    csv_path, case, run = sys.argv[1:]
    out_root = Path(__file__).resolve().parents[2] / 'experiments' / 'experiment3' / 'csvs' / case / f'run{run}'
    try:
        return 0 if extract_vectors(Path(csv_path), out_root, selected) else 1
    except (OSError, ValueError) as error:
        print(f"Extraction failed: {error}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

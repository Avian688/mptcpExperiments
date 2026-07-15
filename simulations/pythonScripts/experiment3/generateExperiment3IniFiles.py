#!/usr/bin/env python3

from __future__ import annotations

import math
import random
from pathlib import Path

MSS_BYTES = 1448
USER_COUNT = 2
PATH_RTT_MS = 100
X_MBPS = 90
T_MBPS = 120
RUNS = range(1, 6)
START_RANDOM_WINDOW_S = 2.0
START_RANDOM_SEED = 3999

PROTOCOLS = {
    "lia": {
        "config": "LiaCoupled",
        "tcp_type": "MpTcp",
        "algorithm_class": "MpTcpLia",
        "description": "LIA",
    },
    "olia": {
        "config": "OliaCoupled",
        "tcp_type": "MpTcp",
        "algorithm_class": "MpTcpOlia",
        "description": "OLIA",
    },
    "balia": {
        "config": "BaliaCoupled",
        "tcp_type": "MpTcp",
        "algorithm_class": "MpTcpBalia",
        "description": "BALIA",
    },
    "mporb_alpha": {
        "config": "MpOrbAlpha",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbSemiCoupledAlpha",
        "description": "MPORB Alpha",
    },
    "mporb_delta": {
        "config": "MpOrbDelta",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbSemiCoupledDelta",
        "description": "MPORB Delta",
    },
}

SCRIPT_DIR = Path(__file__).resolve().parent
SIM_ROOT = SCRIPT_DIR.parents[1]
EXPERIMENT_DIR = SIM_ROOT / "experiments" / "experiment3"


def highest_bdp_packets() -> int:
    return math.ceil(T_MBPS * 1_000_000 * (PATH_RTT_MS / 1000) / (MSS_BYTES * 8))


def initial_ssthresh_bytes() -> int:
    return int(X_MBPS * 1_000_000 * (PATH_RTT_MS / 1000) / 8)


def flow_start_times(run: int) -> list[float]:
    rng = random.Random(START_RANDOM_SEED + run)
    return [rng.uniform(0.1, START_RANDOM_WINDOW_S) for _ in range(USER_COUNT)]


def common_ned_path_line() -> str:
    paths = [
        "../..",
        "../../../src",
        "../../../../mptcp/simulations",
        "../../../../mptcp/src",
        "../../../../mporb/simulations",
        "../../../../mporb/src",
        "../../../../orbtcp/simulations",
        "../../../../orbtcp/src",
        "../../../../cubic/simulations",
        "../../../../cubic/src",
        "../../../../tcpPaced/simulations",
        "../../../../tcpPaced/src",
        "../../../../tcpGoodputApplications/simulations",
        "../../../../tcpGoodputApplications/src",
        "../../../../inet4.5/examples",
        "../../../../inet4.5/showcases",
        "../../../../inet4.5/src",
        "../../../../inet4.5/tests/validation",
        "../../../../inet4.5/tests/networks",
        "../../../../inet4.5/tutorials",
    ]
    return "ned-path = " + ":".join(paths)


def write_common_general(write) -> None:
    queue_packets = highest_bdp_packets()
    lines = (
        "[General]",
        common_ned_path_line(),
        "",
        "network = mptcpexperiments.simulations.experiments.experiment3.oliapareto",
        "sim-time-limit = 100s",
        "record-eventlog = false",
        "cmdenv-express-mode = true",
        "cmdenv-event-banners = false",
        "cmdenv-redirect-output = false",
        "cmdenv-output-file = experiment3Log.txt",
        "cmdenv-log-prefix = %t | %m |",
        "**.cmdenv-log-level = off",
        "",
        "# OLIA motivation: Red y1 crosses both X and T, so each Mbps on y1",
        "# consumes two bottlenecks and reduces achievable aggregate goodput by one Mbps.",
        "# Blue paths: x1=X, x2=T. Red paths: y1=X->T, y2=T.",
        f"# All paths have {PATH_RTT_MS} ms base RTT; X={X_MBPS} Mbps and T={T_MBPS} Mbps.",
        f"# Every queue uses the higher BDP: {queue_packets} packets at MSS {MSS_BYTES}.",
        "**.numberOfSubflows = 2",
        "**.startAllSubflowsAtBeginning = true",
        "**.subflowStartTimes = \"\"",
        "*.configurator.config = xmldoc(\"../scenarios/experiment3/routes.xml\")",
        "*.configurator.addDefaultRoutes = false",
        "*.configurator.addSubnetRoutes = false",
        "*.configurator.optimizeRoutes = false",
        "",
        "**.client[*].numApps = 1",
        "**.client[*].app[0].typename = \"MpTcpSessionApp\"",
        "*.client[0].app[0].connectAddress = \"server[0]\"",
        "*.client[1].app[0].connectAddress = \"server[1]\"",
        "*.client[0].tcp.subflowRemoteAddresses = \"server[0]>blueXExit server[0]>blueTExit\"",
        "*.client[1].tcp.subflowRemoteAddresses = \"server[1]>redXExit server[1]>redTExit\"",
        "**.client[*].app[0].tOpen = 0.1s",
        "**.client[*].app[0].tSend = 0.1s",
        "**.client[*].app[0].tClose = -1s",
        "**.client[*].app[0].sendBytes = 2GB",
        "**.client[*].app[0].dataTransferMode = \"bytecount\"",
        "**.client[*].app[0].statistic-recording = true",
        "",
        "**.server[*].numApps = 1",
        "**.server[*].app[0].typename = \"MpTcpSinkApp\"",
        "**.server[*].app[0].serverThreadModuleType = \"tcpgoodputapplications.applications.tcpapp.TcpGoodputSinkAppThread\"",
        "",
        "**.tcp.advertisedWindow = 200000000",
        "**.tcp.windowScalingSupport = true",
        "**.tcp.windowScalingFactor = -1",
        "**.tcp.increasedIWEnabled = true",
        "**.tcp.delayedAcksEnabled = false",
        "**.tcp.timestampSupport = true",
        "**.tcp.ecnWillingness = false",
        "**.tcp.nagleEnabled = true",
        "**.tcp.stopOperationTimeout = 4000s",
        f"**.tcp.mss = {MSS_BYTES}",
        "**.tcp.sackSupport = true",
        f"**.tcp.initialSsthresh = {initial_ssthresh_bytes()}",
        "**.tcp.sendQueueLimit = 4MiB",
        "**.schedulerMode = \"default\"",
        "",
        "**.goodputInterval = 0.5s",
        "**.throughputInterval = 0.5s",
        "**.**.goodput:vector(removeRepeats).vector-recording = true",
        "**.**.goodput.result-recording-modes = vector(removeRepeats)",
        "**.**.tcp.conn-*.throughput:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.cwnd:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.retransmissionRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.liaAlpha:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.oliaEpsilon:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.baliaAi:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.baliaMd:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledAlphaSubflowRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledAlphaConnectionRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledAlphaRateShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledDeltaTargetShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledDeltaRateShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledDeltaAiShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.**.result-recording-modes = vector(removeRepeats)",
        "**.xIngress.ppp[0].queue.queueLength:vector(removeRepeats).vector-recording = true",
        "**.tIngress.ppp[0].queue.queueLength:vector(removeRepeats).vector-recording = true",
        "**.xIngress.ppp[0].queue.queueLength.result-recording-modes = vector(removeRepeats)",
        "**.tIngress.ppp[0].queue.queueLength.result-recording-modes = vector(removeRepeats)",
        f"**.ppp[*].queue.packetCapacity = {queue_packets}",
        "**.scalar-recording = false",
        "**.vector-recording = false",
        "**.bin-recording = false",
        "",
    )
    for line in lines:
        write(line)


def write_protocol_settings(write, protocol: str, settings: dict[str, str]) -> None:
    write(f'**.tcp.typename = "{settings["tcp_type"]}"')
    write(f'**.tcp.tcpAlgorithmClass = "{settings["algorithm_class"]}"')
    is_mporb = settings["tcp_type"] == "MpOrb"
    if is_mporb:
        write("# Specific IntQueue assignments must precede the broad fallback.")
        write('**.xIngress.ppp[0].queue.typename = "IntQueue"')
        write('**.tIngress.ppp[0].queue.typename = "IntQueue"')
    write('**.ppp[*].queue.typename = "DropTailQueue"')
    write('**.ppp[*].queue.dropperClass = "inet::queueing::PacketAtCollectionEndDropper"')
    if is_mporb:
        write("**.additiveIncreasePercent = 0.05")
        write("**.eta = 0.95")
        write("**.alpha = 0" if protocol in {"mporb_alpha", "mporb_delta"} else "**.alpha = 0.01")
        write("**.fixedAvgRTTVal = 0")
    write()


def write_config(write, settings: dict[str, str], run: int) -> None:
    config = f'{settings["config"]}_Run{run}'
    write(f"[Config {config}]")
    write("extends = General")
    write(f'description = "{settings["description"]}; OLIA Pareto test, run {run}."')
    write(f"seed-set = {run}")
    for user, start_time in enumerate(flow_start_times(run)):
        write(f"*.client[{user}].app[0].tOpen = {start_time:.6f}s")
        write(f"*.client[{user}].app[0].tSend = {start_time:.6f}s")
    write(f'output-vector-file = "results/{config}-#0.vec"')
    write(f'output-scalar-file = "results/{config}-#0.sca"')
    write()


def main() -> None:
    if highest_bdp_packets() != 1036:
        raise RuntimeError(f"unexpected higher-BDP packet count: {highest_bdp_packets()}")

    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    for protocol, settings in PROTOCOLS.items():
        out_path = EXPERIMENT_DIR / f"experiment3_{protocol}.ini"
        with out_path.open("w", encoding="utf-8") as output:
            def write(line: str = "") -> None:
                output.write(line + "\n")

            write_common_general(write)
            write_protocol_settings(write, protocol, settings)
            for run in RUNS:
                write_config(write, settings, run)
        print(f"Generated {out_path}.")


if __name__ == "__main__":
    main()

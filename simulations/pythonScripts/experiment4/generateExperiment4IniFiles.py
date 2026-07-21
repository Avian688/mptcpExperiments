#!/usr/bin/env python3

from __future__ import annotations

import math
import random
from pathlib import Path

MSS_BYTES = 1448
PATH_MBPS = 20
PATH_RTT_MS = 20
BACKGROUND_FLOW_COUNT = 5
BACKGROUND_INITIAL_SSTHRESH_BYTES = 40_000
COMPETITION_START_S = 40
COMPETITION_END_S = 80
SIM_TIME_LIMIT_S = 200
RUNS = range(1, 6)
START_RANDOM_SEED = 4999

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
    "mporb": {
        "config": "MpOrbUncoupled",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbUncoupled",
        "description": "MPORB Uncoupled",
    },
    "mporb_alpha": {
        "config": "MpOrbAlpha",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbSemiCoupledAlpha",
        "description": "MPORB Alpha",
    },
    "mporb_olia": {
        "config": "MpOrbOlia",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbOlia",
        "description": "MPORB OLIA",
    },
    "mporb_beta": {
        "config": "MpOrbBeta",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbSemiCoupledBeta",
        "description": "MPORB Beta",
    },
    "mporb_delta": {
        "config": "MpOrbDelta",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbSemiCoupledDelta",
        "description": "MPORB Delta",
    },
    "mporb_epsilon": {
        "config": "MpOrbEpsilon",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbSemiCoupledEpsilon",
        "description": "MPORB Epsilon",
    },
    "mporb_zeta": {
        "config": "MpOrbZeta",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbSemiCoupledZeta",
        "description": "MPORB Zeta",
    },
}

SCRIPT_DIR = Path(__file__).resolve().parent
SIM_ROOT = SCRIPT_DIR.parents[1]
EXPERIMENT_DIR = SIM_ROOT / "experiments" / "experiment4"


def bdp_packets() -> int:
    return math.ceil(PATH_MBPS * 1_000_000 * (PATH_RTT_MS / 1000) / (MSS_BYTES * 8))


def flow_start_time(run: int) -> float:
    return random.Random(START_RANDOM_SEED + run).uniform(0.1, 2.0)


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
    queue_packets = bdp_packets()
    lines = (
        "[General]",
        common_ned_path_line(),
        "",
        "network = mptcpexperiments.simulations.experiments.experiment4.baliaresponsiveness",
        f"sim-time-limit = {SIM_TIME_LIMIT_S}s",
        "record-eventlog = false",
        "cmdenv-express-mode = true",
        "cmdenv-event-banners = false",
        "cmdenv-redirect-output = false",
        "cmdenv-output-file = experiment4Log.txt",
        "cmdenv-log-prefix = %t | %m |",
        "**.cmdenv-log-level = off",
        "",
        f"# BALIA responsiveness test: two fixed {PATH_MBPS} Mbps, {PATH_RTT_MS} ms paths.",
        f"# Five one-subflow connections using the tested CC join path 2 together at "
        f"{COMPETITION_START_S} s, then stop admitting new data at {COMPETITION_END_S} s.",
        f"# Every queue uses the highest path BDP: {queue_packets} packets at MSS {MSS_BYTES}.",
        "*.backgroundClient[*].app[0].numberOfSubflows = 1",
        "*.backgroundServer[*].app[0].numberOfSubflows = 1",
        "*.backgroundClient[*].tcp.conn-*.numberOfSubflows = 1",
        "*.backgroundServer[*].tcp.conn-*.numberOfSubflows = 1",
        f"*.backgroundClient[*].tcp.initialSsthresh = {BACKGROUND_INITIAL_SSTHRESH_BYTES}",
        "**.numberOfSubflows = 2",
        "**.startAllSubflowsAtBeginning = true",
        "**.subflowStartTimes = \"\"",
        "*.configurator.config = xml(\"<config><interface hosts='**' address='10.x.x.x' netmask='255.x.x.x'/><autoroute metric='delay'/></config>\")",
        "*.configurator.addDefaultRoutes = false",
        "*.configurator.addSubnetRoutes = false",
        "*.configurator.optimizeRoutes = false",
        "*.scenarioManager.script = xmldoc(\"../scenarios/experiment4/conditions.xml\")",
        "",
        "*.client[0].numApps = 1",
        "*.client[0].app[0].typename = \"MpTcpSessionApp\"",
        "*.client[0].app[0].connectAddress = \"server[0]\"",
        "*.client[0].tcp.subflowRemoteAddresses = \"server[0]>p1Egress server[0]>p2Egress\"",
        "*.client[0].app[0].tOpen = 0.1s",
        "*.client[0].app[0].tSend = 0.1s",
        "*.client[0].app[0].tClose = -1s",
        "*.client[0].app[0].sendBytes = 2GB",
        "*.client[0].app[0].dataTransferMode = \"bytecount\"",
        "",
        "*.server[0].numApps = 1",
        "*.server[0].app[0].typename = \"MpTcpSinkApp\"",
        "*.server[0].app[0].serverThreadModuleType = \"tcpgoodputapplications.applications.tcpapp.TcpGoodputSinkAppThread\"",
        "",
        "*.backgroundClient[*].numApps = 1",
        "*.backgroundClient[*].app[0].typename = \"MpTcpSessionApp\"",
        "*.backgroundClient[*].app[0].connectPort = 1000",
        "*.backgroundClient[*].app[0].tClose = -1s",
        "*.backgroundClient[*].app[0].sendBytes = 2GB",
        "*.backgroundClient[*].app[0].dataTransferMode = \"bytecount\"",
        "*.backgroundClient[0].app[0].connectAddress = \"backgroundServer[0]\"",
        "*.backgroundClient[1].app[0].connectAddress = \"backgroundServer[1]\"",
        "*.backgroundClient[2].app[0].connectAddress = \"backgroundServer[2]\"",
        "*.backgroundClient[3].app[0].connectAddress = \"backgroundServer[3]\"",
        "*.backgroundClient[4].app[0].connectAddress = \"backgroundServer[4]\"",
        "",
        "*.backgroundServer[*].numApps = 1",
        "*.backgroundServer[*].app[0].typename = \"MpTcpSinkApp\"",
        "*.backgroundServer[*].app[0].localPort = 1000",
        "*.backgroundServer[*].app[0].serverThreadModuleType = \"tcpgoodputapplications.applications.tcpapp.TcpGoodputSinkAppThread\"",
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
        "# Exercise the updated SACK scoreboard for every MPTCP subflow.",
        "**.tcp.updatedSackEnabled = true",
        "*.client[0].tcp.sendQueueLimit = 4MiB",
        "*.server[0].tcp.sendQueueLimit = 4MiB",
        "*.client[0].tcp.schedulerMode = \"default\"",
        "*.server[0].tcp.schedulerMode = \"default\"",
        "",
        "**.goodputInterval = 0.5s",
        "**.throughputInterval = 0.5s",
        "**.**.tcp.conn-temp.**.statistic-recording = false",
        "**.**.goodput.statistic-recording = true",
        "**.**.goodput:vector(removeRepeats).vector-recording = true",
        "**.**.goodput.result-recording-modes = vector(removeRepeats)",
        "**.**.tcp.conn-*.throughput.statistic-recording = true",
        "**.**.tcp.conn-*.cwnd.statistic-recording = true",
        "**.**.tcp.conn-*.cwndLimited.statistic-recording = true",
        "**.**.tcp.conn-*.lossRecovery.statistic-recording = true",
        "**.**.tcp.conn-*.numRtos.statistic-recording = true",
        "**.**.tcp.conn-*.retransmissionRate.statistic-recording = true",
        "**.**.tcp.conn-*.liaAlpha.statistic-recording = true",
        "**.**.tcp.conn-*.oliaEpsilon.statistic-recording = true",
        "**.**.tcp.conn-*.baliaAi.statistic-recording = true",
        "**.**.tcp.conn-*.baliaMd.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledAlphaSubflowRate.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledAlphaConnectionRate.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledAlphaRateShare.statistic-recording = true",
        "**.**.tcp.conn-*.mpOrbOliaBestPath.statistic-recording = true",
        "**.**.tcp.conn-*.mpOrbOliaMaxWindowPath.statistic-recording = true",
        "**.**.tcp.conn-*.mpOrbOliaCorrection.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledBetaFairRate.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledBetaTotalFairRate.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledBetaFairRateShare.statistic-recording = true",
        "**.**.tcp.conn-*.holBlockedBytes.statistic-recording = true",
        "**.**.tcp.conn-*.metaReinjectedBytes.statistic-recording = true",
        "**.**.tcp.conn-*.metaReinjections.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledDeltaTargetShare.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledDeltaRateShare.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledDeltaAiShare.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledEpsilonPathCost.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledEpsilonDesiredShare.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledEpsilonRateShare.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledEpsilonRedistribution.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledZetaPathCost.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledZetaPathWeight.statistic-recording = true",
        "**.**.tcp.conn-*.semiCoupledZetaConnectionAiRate.statistic-recording = true",
        "**.**.tcp.conn-*.throughput:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.cwnd:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.cwndLimited:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.lossRecovery:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.numRtos:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.retransmissionRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.liaAlpha:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.oliaEpsilon:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.baliaAi:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.baliaMd:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledAlphaSubflowRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledAlphaConnectionRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledAlphaRateShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.mpOrbOliaBestPath:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.mpOrbOliaMaxWindowPath:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.mpOrbOliaCorrection:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledBetaFairRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledBetaTotalFairRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledBetaFairRateShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.holBlockedBytes:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.metaReinjectedBytes:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.metaReinjections:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledDeltaTargetShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledDeltaRateShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledDeltaAiShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledEpsilonPathCost:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledEpsilonDesiredShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledEpsilonRateShare:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledEpsilonRedistribution:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledZetaPathCost:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledZetaPathWeight:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledZetaConnectionAiRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.**.result-recording-modes = vector(removeRepeats)",
        "**.p1Ingress.ppp[0].queue.queueLength.statistic-recording = true",
        "**.p2Ingress.ppp[0].queue.queueLength.statistic-recording = true",
        "**.p1Ingress.ppp[0].queue.queueLength:vector(removeRepeats).vector-recording = true",
        "**.p2Ingress.ppp[0].queue.queueLength:vector(removeRepeats).vector-recording = true",
        "**.p1Ingress.ppp[0].queue.queueLength.result-recording-modes = vector(removeRepeats)",
        "**.p2Ingress.ppp[0].queue.queueLength.result-recording-modes = vector(removeRepeats)",
        f"**.ppp[*].queue.packetCapacity = {queue_packets}",
        "**.statistic-recording = false",
        "**.scalar-recording = false",
        "**.vector-recording = false",
        "**.bin-recording = false",
        "",
    )
    for line in lines:
        write(line)


def write_protocol_settings(write, protocol: str, settings: dict[str, str]) -> None:
    write(f'*.client[0].tcp.typename = "{settings["tcp_type"]}"')
    write(f'*.server[0].tcp.typename = "{settings["tcp_type"]}"')
    write(f'*.client[0].tcp.tcpAlgorithmClass = "{settings["algorithm_class"]}"')
    write(f'*.server[0].tcp.tcpAlgorithmClass = "{settings["algorithm_class"]}"')
    write(f'*.backgroundClient[*].tcp.typename = "{settings["tcp_type"]}"')
    write(f'*.backgroundServer[*].tcp.typename = "{settings["tcp_type"]}"')
    write(f'*.backgroundClient[*].tcp.tcpAlgorithmClass = "{settings["algorithm_class"]}"')
    write(f'*.backgroundServer[*].tcp.tcpAlgorithmClass = "{settings["algorithm_class"]}"')
    is_mporb = settings["tcp_type"] == "MpOrb"
    if is_mporb:
        write("# Specific IntQueue assignments must precede the broad fallback.")
        write('**.p1Ingress.ppp[0].queue.typename = "IntQueue"')
        write('**.p2Ingress.ppp[0].queue.typename = "IntQueue"')
    write('**.ppp[*].queue.typename = "DropTailQueue"')
    write('**.ppp[*].queue.dropperClass = "inet::queueing::PacketAtCollectionEndDropper"')
    if is_mporb:
        write("**.additiveIncreasePercent = 0.05")
        write("**.eta = 0.95")
        if protocol in {"mporb_alpha", "mporb_olia", "mporb_beta", "mporb_delta", "mporb_epsilon", "mporb_zeta"}:
            write("# Zero selects OrbCC's time-normalized alpha = tau / averageRTT.")
            write("**.alpha = 0")
        else:
            write("**.alpha = 0.01")
        write("**.fixedAvgRTTVal = 0")
    write()


def write_config(write, settings: dict[str, str], run: int) -> None:
    config = f'{settings["config"]}_Run{run}'
    start_time = flow_start_time(run)
    write(f"[Config {config}]")
    write("extends = General")
    write(f'description = "{settings["description"]}; BALIA responsiveness test, run {run}."')
    write(f"seed-set = {run}")
    write(f"*.client[0].app[0].tOpen = {start_time:.6f}s")
    write(f"*.client[0].app[0].tSend = {start_time:.6f}s")
    for index in range(BACKGROUND_FLOW_COUNT):
        write(f"*.backgroundClient[{index}].app[0].tOpen = {COMPETITION_START_S}s")
        write(f"*.backgroundClient[{index}].app[0].tSend = {COMPETITION_START_S}s")
    write(f'output-vector-file = "results/{config}-#0.vec"')
    write(f'output-scalar-file = "results/{config}-#0.sca"')
    write()


def main() -> None:
    if bdp_packets() != 35:
        raise RuntimeError(f"unexpected BDP packet count: {bdp_packets()}")

    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    for protocol, settings in PROTOCOLS.items():
        out_path = EXPERIMENT_DIR / f"experiment4_{protocol}.ini"
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

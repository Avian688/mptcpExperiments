#!/usr/bin/env python3

from __future__ import annotations

import math
import random
import xml.etree.ElementTree as ET
from pathlib import Path

MSS_BYTES = 1448
USERS_PER_TYPE = 4
USER_COUNT = 2 * USERS_PER_TYPE
PATH_RTT_MS = 50
X_MBPS = 27
T_MBPS = 36
SIM_TIME_LIMIT_S = 150
RUNS = range(1, 6)
START_RANDOM_WINDOW_S = 0.5
START_RANDOM_SEED = 3999
RED_Y1_START_DELAY_S = 30
ONE_MSS_INITIAL_SSTHRESH_PROTOCOLS = {"olia", "balia"}

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
EXPERIMENT_DIR = SIM_ROOT / "experiments" / "experiment3"
SCENARIO_DIR = SIM_ROOT / "experiments" / "scenarios" / "experiment3"


def highest_bdp_packets() -> int:
    return math.ceil(T_MBPS * 1_000_000 * (PATH_RTT_MS / 1000) / (MSS_BYTES * 8))


def initial_ssthresh_bytes(protocol: str) -> int:
    if protocol in ONE_MSS_INITIAL_SSTHRESH_PROTOCOLS:
        return MSS_BYTES

    packets = math.ceil(
        X_MBPS
        * 1_000_000
        * (PATH_RTT_MS / 1000)
        / (MSS_BYTES * 8 * USERS_PER_TYPE)
    )
    return packets * MSS_BYTES


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


def client_configuration_lines() -> list[str]:
    lines: list[str] = []
    for user in range(USER_COUNT):
        if user < USERS_PER_TYPE:
            remote_addresses = f"server[{user}]>blueXExit server[{user}]>blueTExit"
        else:
            remote_addresses = f"server[{user}]>redTExit server[{user}]>redXExit"
        lines.extend(
            [
                f'*.client[{user}].app[0].connectAddress = "server[{user}]"',
                f'*.client[{user}].tcp.subflowRemoteAddresses = "{remote_addresses}"',
            ]
        )
    return lines


def write_routes_xml() -> Path:
    SCENARIO_DIR.mkdir(parents=True, exist_ok=True)
    root = ET.Element("config")
    ET.SubElement(
        root,
        "interface",
        {"hosts": "**", "address": "10.x.x.x", "netmask": "255.x.x.x"},
    )
    root.append(
        ET.Comment(
            " Routers and servers use shortest paths. Explicit client routes keep "
            "Red y1 on X then T instead of collapsing onto y2. "
        )
    )
    ET.SubElement(
        root,
        "autoroute",
        {
            "sourceHosts": (
                "xIngress xEgress tIngress tEgress blueXExit blueTExit "
                "redXExit redTExit server[*]"
            ),
            "metric": "delay",
        },
    )

    for user in range(USER_COUNT):
        if user < USERS_PER_TYPE:
            exits = (("blueXExit", "xIngress"), ("blueTExit", "tIngress"))
        else:
            exits = (("redXExit", "xIngress"), ("redTExit", "tIngress"))
        for exit_router, ingress in exits:
            ET.SubElement(
                root,
                "route",
                {
                    "hosts": f"client[{user}]",
                    "destination": f"server[{user}]>{exit_router}",
                    "netmask": "/32",
                    "gateway": f"{ingress}>client[{user}]",
                },
            )

    ET.indent(root, space="    ")
    path = SCENARIO_DIR / "routes.xml"
    ET.ElementTree(root).write(path, encoding="unicode")
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    return path


def write_common_general(write, protocol: str) -> None:
    queue_packets = highest_bdp_packets()
    lines = (
        "[General]",
        common_ned_path_line(),
        "",
        "network = mptcpexperiments.simulations.experiments.experiment3.oliapareto",
        f"sim-time-limit = {SIM_TIME_LIMIT_S}s",
        "record-eventlog = false",
        "cmdenv-express-mode = true",
        "cmdenv-event-banners = false",
        "cmdenv-redirect-output = false",
        "cmdenv-output-file = experiment3Log.txt",
        "cmdenv-log-prefix = %t | %m |",
        "**.cmdenv-log-level = off",
        "",
        f"# Compact Scenario B: {USERS_PER_TYPE} Blue and {USERS_PER_TYPE} Red MPTCP connections.",
        "# OLIA motivation: Red y1 crosses both X and T, so each Mbps on y1",
        "# consumes two bottlenecks and reduces achievable aggregate goodput by one Mbps.",
        "# Blue paths: x1=X, x2=T. Red paths: y1=X->T, y2=T.",
        f"# Blue opens both paths immediately; Red opens y2 first and y1 after {RED_Y1_START_DELAY_S} s.",
        f"# All paths have {PATH_RTT_MS} ms base RTT; X={X_MBPS} Mbps and T={T_MBPS} Mbps.",
        f"# Every queue uses the higher BDP: {queue_packets} packets at MSS {MSS_BYTES}.",
        "**.numberOfSubflows = 2",
        "**.startAllSubflowsAtBeginning = true",
        *(
            f'*.client[{user}].tcp.subflowStartTimes = "0s {RED_Y1_START_DELAY_S}s"'
            for user in range(USERS_PER_TYPE, USER_COUNT)
        ),
        "**.subflowStartTimes = \"\"",
        "*.configurator.config = xmldoc(\"../scenarios/experiment3/routes.xml\")",
        "*.configurator.addDefaultRoutes = false",
        "*.configurator.addSubnetRoutes = false",
        "*.configurator.optimizeRoutes = false",
        "",
        "**.client[*].numApps = 1",
        "**.client[*].app[0].typename = \"MpTcpSessionApp\"",
        *client_configuration_lines(),
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
        f"**.tcp.initialSsthresh = {initial_ssthresh_bytes(protocol)}",
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
        "**.**.tcp.conn-*.mpOrbOliaBestPath:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.mpOrbOliaMaxWindowPath:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.mpOrbOliaCorrection:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledBetaFairRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledBetaTotalFairRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.semiCoupledBetaFairRateShare:vector(removeRepeats).vector-recording = true",
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
        write("**.alpha = 0" if protocol in {"mporb_alpha", "mporb_olia", "mporb_beta", "mporb_delta", "mporb_epsilon", "mporb_zeta"} else "**.alpha = 0.01")
        write("**.fixedAvgRTTVal = 0")
    write()


def write_config(write, settings: dict[str, str], run: int) -> None:
    config = f'{settings["config"]}_Run{run}'
    write(f"[Config {config}]")
    write("extends = General")
    write(f'description = "{settings["description"]}; all-MPTCP Scenario B, run {run}."')
    write(f"seed-set = {run}")
    for user, start_time in enumerate(flow_start_times(run)):
        write(f"*.client[{user}].app[0].tOpen = {start_time:.6f}s")
        write(f"*.client[{user}].app[0].tSend = {start_time:.6f}s")
    write(f'output-vector-file = "results/{config}-#0.vec"')
    write(f'output-scalar-file = "results/{config}-#0.sca"')
    write()


def main() -> None:
    if highest_bdp_packets() != 156:
        raise RuntimeError(f"unexpected higher-BDP packet count: {highest_bdp_packets()}")

    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    routes_path = write_routes_xml()
    print(f"Generated {routes_path}.")
    for protocol, settings in PROTOCOLS.items():
        out_path = EXPERIMENT_DIR / f"experiment3_{protocol}.ini"
        with out_path.open("w", encoding="utf-8") as output:
            def write(line: str = "") -> None:
                output.write(line + "\n")

            write_common_general(write, protocol)
            write_protocol_settings(write, protocol, settings)
            for run in RUNS:
                write_config(write, settings, run)
        print(f"Generated {out_path}.")


if __name__ == "__main__":
    main()

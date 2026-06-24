#!/usr/bin/env python3

from __future__ import annotations

import math
import random
from pathlib import Path

MSS_BYTES = 1448
PATH_MBPS = 100
PATH_RTT_MS = 60
RUNS = range(1, 6)
START_RANDOM_WINDOW_S = 5.0
START_RANDOM_SEED = 2999

PROTOCOLS = {
    "cubic": {
        "config": "CubicUncoupled",
        "tcp_type": "MpTcp",
        "algorithm_class": "MpTcpMetaCubic",
        "description": "Uncoupled MPTCP CUBIC",
    },
    "mporb": {
        "config": "MpOrbUncoupled",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbFlavour",
        "description": "Uncoupled MPORB/ORBCC",
    },
    "olia": {
        "config": "OliaCoupled",
        "tcp_type": "MpTcp",
        "algorithm_class": "MpTcpOlia",
        "description": "Coupled MPTCP OLIA",
    },
    "balia": {
        "config": "BaliaCoupled",
        "tcp_type": "MpTcp",
        "algorithm_class": "MpTcpBalia",
        "description": "Coupled MPTCP BALIA",
    },
}

SCRIPT_DIR = Path(__file__).resolve().parent
SIM_ROOT = SCRIPT_DIR.parents[1]
EXPERIMENT_DIR = SIM_ROOT / "experiments" / "experiment2"


def bdp_packets() -> int:
    return math.ceil(PATH_MBPS * 1_000_000 * (PATH_RTT_MS / 1000) / (MSS_BYTES * 8))


def flow_start_times(run: int, count: int) -> list[float]:
    rng = random.Random(START_RANDOM_SEED + run)
    return [rng.uniform(0.0, START_RANDOM_WINDOW_S) for _ in range(count)]


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
    lines = (
        "[General]",
        common_ned_path_line(),
        "",
        "network = mptcpexperiments.simulations.experiments.experiment2.sharedleopaths",
        "sim-time-limit = 120s",
        "record-eventlog = false",
        "cmdenv-express-mode = true",
        "cmdenv-event-banners = false",
        "cmdenv-redirect-output = false",
        "cmdenv-output-file = experiment2Log.txt",
        "cmdenv-log-prefix = %t | %m |",
        "**.cmdenv-log-level = off",
        "",
        "# A uses paths 1-4; B uses 1,2,5,6; C uses 3,4,7,8.",
        "# All three connections have four subflows.",
        "# All eight paths are 60 ms / 100 Mbps with one-BDP (518 packet) queues.",
        f"# Run configs start all three users uniformly in the first {START_RANDOM_WINDOW_S:g} seconds.",
        "**.numberOfClientServers = 3",
        "**.numberOfSubflows = 4",
        "**.startAllSubflowsAtBeginning = true",
        "**.subflowStartTimes = \"\"",
        "*.configurator.config = xml(\"<config><interface hosts='**' address='10.x.x.x' netmask='255.x.x.x'/><autoroute metric='delay'/></config>\")",
        "*.configurator.addDefaultRoutes = false",
        "*.configurator.addSubnetRoutes = false",
        "*.configurator.optimizeRoutes = false",
        "",
        "**.client[*].numApps = 1",
        "**.client[*].app[0].typename = \"MpTcpSessionApp\"",
        "*.client[0].app[0].connectAddress = \"server[0]\"",
        "*.client[1].app[0].connectAddress = \"server[1]\"",
        "*.client[2].app[0].connectAddress = \"server[2]\"",
        "*.client[0].tcp.subflowRemoteAddresses = \"server[0]>router2[0] server[0]>router2[1] server[0]>router2[2] server[0]>router2[3]\"",
        "*.client[1].tcp.subflowRemoteAddresses = \"server[1]>router2[0] server[1]>router2[1] server[1]>router2[4] server[1]>router2[5]\"",
        "*.client[2].tcp.subflowRemoteAddresses = \"server[2]>router2[2] server[2]>router2[3] server[2]>router2[6] server[2]>router2[7]\"",
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
        "**.tcp.mss = 1448",
        "**.tcp.sackSupport = true",
        "**.tcp.initialSsthresh = 5792000",
        "**.schedulerMode = \"default\"",
        "",
        "**.goodputInterval = 0.5s",
        "**.throughputInterval = 0.5s",
        "**.**.goodput:vector(removeRepeats).vector-recording = true",
        "**.**.goodput.result-recording-modes = vector(removeRepeats)",
        "**.**.tcp.conn-*.throughput:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.cwnd:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.retransmissionRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.metaReinjectedBytes:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.metaReinjections:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.**.result-recording-modes = vector(removeRepeats)",
        "**.**.queue.queueLength:vector(removeRepeats).vector-recording = true",
        "**.**.queue.queueLength.result-recording-modes = vector(removeRepeats)",
        "**.ppp[*].queue.packetCapacity = 518",
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
    if protocol == "mporb":
        write("# ORBCC requires INT telemetry on every forward bottleneck.")
        write("# Keep these before the broad DropTail fallback: earlier matching lines have priority in these ini files.")
        for path in range(4):
            write(f'**.router1[{path}].ppp[2].queue.typename = "IntQueue"')
        for path in range(4, 8):
            write(f'**.router1[{path}].ppp[1].queue.typename = "IntQueue"')
    write('**.ppp[*].queue.typename = "DropTailQueue"')
    write('**.ppp[*].queue.dropperClass = "inet::queueing::PacketAtCollectionEndDropper"')
    if protocol == "mporb":
        write("**.additiveIncreasePercent = 0.05")
        write("**.eta = 0.95")
        write("**.alpha = 0.01")
        write("**.fixedAvgRTTVal = 0")
    write()


def write_config(write, settings: dict[str, str], run: int) -> None:
    config = f'{settings["config"]}_Run{run}'
    start_times = flow_start_times(run, 3)
    write(f"[Config {config}]")
    write("extends = General")
    write(f'description = "{settings["description"]}; equal path RTT/capacity, four subflows per connection, run {run}."')
    write(f"seed-set = {run}")
    for user, start_time in enumerate(start_times):
        write(f"*.client[{user}].app[0].tOpen = {start_time:.6f}s")
        write(f"*.client[{user}].app[0].tSend = {start_time:.6f}s")
    write(f'output-vector-file = "results/{config}-#0.vec"')
    write(f'output-scalar-file = "results/{config}-#0.sca"')
    write()


def main() -> None:
    expected_packets = bdp_packets()
    if expected_packets != 518:
        raise RuntimeError(f"unexpected BDP packet count: {expected_packets}")

    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    for protocol, settings in PROTOCOLS.items():
        out_path = EXPERIMENT_DIR / f"experiment2_{protocol}.ini"
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

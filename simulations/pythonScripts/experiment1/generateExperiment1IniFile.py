#!/usr/bin/env python3

from __future__ import annotations

import math
from pathlib import Path

RTT_SWEEP_MS = [20, 40, 60, 80, 100, 120, 140, 160, 180]
MSS_BYTES = 1448
FIXED_PATH_RTT_MS = 20
FIXED_PATH_DATARATE_MBPS = 10
VARIABLE_PATH_DATARATE_MBPS = 100
FIXED_PATH_DATARATE = f"{FIXED_PATH_DATARATE_MBPS}Mbps"
VARIABLE_PATH_DATARATE = f"{VARIABLE_PATH_DATARATE_MBPS}Mbps"

SCHEDULERS = [
    ("Default", "default"),
    ("LowestRtt", "lowestRtt"),
]

PROTOCOLS = {
    "cubic": {
        "title": "Cubic",
        "tcp_type": "MpTcp",
        "algorithm_class": "MpTcpMetaCubic",
        "description": "MPTCP CUBIC",
    },
    "mporb": {
        "title": "MpOrb",
        "tcp_type": "MpOrb",
        "algorithm_class": "MpOrbFlavour",
        "description": "MPORB/ORBCC",
    },
}

SCRIPT_DIR = Path(__file__).resolve().parent
SIM_ROOT = SCRIPT_DIR.parents[1]
EXPERIMENT_DIR = SIM_ROOT / "experiments" / "experiment1"


def bdp_packets(datarate_mbps: int, rtt_ms: int) -> int:
    return math.ceil(datarate_mbps * 1_000_000 * (rtt_ms / 1000) / (MSS_BYTES * 8))


def queue_packets_for(variable_rtt_ms: int) -> int:
    fixed = (FIXED_PATH_RTT_MS, bdp_packets(FIXED_PATH_DATARATE_MBPS, FIXED_PATH_RTT_MS))
    variable = (variable_rtt_ms, bdp_packets(VARIABLE_PATH_DATARATE_MBPS, variable_rtt_ms))
    higher_rtt = max(fixed[0], variable[0])
    return max(packets for rtt_ms, packets in (fixed, variable) if rtt_ms == higher_rtt)


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


def write_common_general(w) -> None:
    for line in (
        "[General]",
        common_ned_path_line(),
        "",
        "network = mptcpexperiments.simulations.experiments.experiment1.schedulernegativetwopaths",
        "sim-time-limit = 120s",
        "record-eventlog = false",
        "cmdenv-express-mode = true",
        "cmdenv-event-banners = false",
        "cmdenv-redirect-output = false",
        "cmdenv-output-file = dctcpLog.txt",
        "cmdenv-log-prefix = %t | %m |",
        "**.cmdenv-log-level = off",
        "",
        "# Path 0 is fixed at 20 ms RTT / 10 Mbps.",
        "# Path 1 is swept from 20 ms to 180 ms RTT at 100 Mbps.",
        "# Each config sets queue capacity to the BDP of that run's higher-RTT path.",
        "# Example: 100 Mbps * 180 ms = ceil(18,000,000 / (1448 * 8)) = 1554 packets.",
        "**.numberOfClientServers = 1",
        "**.numberOfSubflows = 2",
        "**.startAllSubflowsAtBeginning = true",
        "**.subflowStartTimes = \"\"",
        f"**.fixedPathRtt = {FIXED_PATH_RTT_MS}ms",
        f"**.fixedPathDatarate = {FIXED_PATH_DATARATE}",
        f"**.variablePathDatarate = {VARIABLE_PATH_DATARATE}",
        "*.configurator.config = xml(\"<config><interface hosts='**' address='10.x.x.x' netmask='255.x.x.x'/><autoroute metric='delay'/></config>\")",
        "*.configurator.addDefaultRoutes = false",
        "*.configurator.addSubnetRoutes = false",
        "*.configurator.optimizeRoutes = false",
        "",
        "**.client[*].numApps = 1",
        "**.client[*].app[0].typename = \"MpTcpSessionApp\"",
        "*.client[0].app[0].connectAddress = \"server[0]\"",
        "*.client[0].tcp.subflowRemoteAddresses = \"server[0]>router2a server[0]>router2b\"",
        "*.client[0].app[0].tOpen = 0.1s",
        "*.client[0].app[0].tSend = 0.1s",
        "*.client[0].app[0].tClose = -1s",
        "*.client[0].app[0].sendBytes = 2GB",
        "*.client[0].app[0].dataTransferMode = \"bytecount\"",
        "*.client[0].app[0].statistic-recording = true",
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
        "",
        "**.goodputInterval = 0.5s",
        "**.throughputInterval = 0.5s",
        "",
        "**.**.goodput:vector(removeRepeats).vector-recording = true",
        "**.**.goodput.result-recording-modes = vector(removeRepeats)",
        "**.**.tcp.conn-*.throughput:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.cwnd:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.rtt:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.srtt:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.mbytesInFlight:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.retransmissionRate:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.holBlockedBytes:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.metaExpectedDsn:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.metaArrivedDsnStart:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.metaDsnGapBytes:vector(removeRepeats).vector-recording = true",
        "**.**.tcp.conn-*.**.result-recording-modes = vector(removeRepeats)",
        "**.**.queue.queueLength:vector(removeRepeats).vector-recording = true",
        "**.**.queue.queueLength.result-recording-modes = vector(removeRepeats)",
        "**.**.queue.queueBitLength:vector(removeRepeats).vector-recording = true",
        "**.**.queue.queueingTime:vector.vector-recording = true",
        "**.scalar-recording = false",
        "**.vector-recording = false",
        "**.bin-recording = false",
        "",
    ):
        w(line)


def write_protocol_general(w, protocol: str, settings: dict[str, str]) -> None:
    w(f'**.tcp.typename = "{settings["tcp_type"]}"')
    w(f'**.tcp.tcpAlgorithmClass = "{settings["algorithm_class"]}"')
    if protocol == "mporb":
        w("# ORBCC needs IntQueue on the forward bottlenecks to append INT queue telemetry.")
        w("# Keep these before the broad DropTail fallback so the specific queues are created as IntQueue.")
        w('**.router1a.ppp[1].queue.typename = "IntQueue"')
        w('**.router1b.ppp[1].queue.typename = "IntQueue"')
    w('**.ppp[*].queue.typename = "DropTailQueue"')
    w('**.ppp[*].queue.dropperClass = "inet::queueing::PacketAtCollectionEndDropper"')
    if protocol == "mporb":
        w("**.additiveIncreasePercent = 0.05")
        w("**.eta = 0.95")
        w("**.alpha = 0.01")
        w("**.fixedAvgRTTVal = 0")
    w()


def write_config(w, settings: dict[str, str], scheduler_title: str, scheduler_mode: str, rtt_ms: int) -> None:
    config_name = f"{settings['title']}{scheduler_title}_{rtt_ms}ms"
    w(f"[Config {config_name}]")
    w("extends = General")
    w(f'description = "{settings["description"]}, {scheduler_mode} scheduler, variable path {rtt_ms} ms RTT."')
    w(f'**.schedulerMode = "{scheduler_mode}"')
    w(f"**.variablePathRtt = {rtt_ms}ms")
    w(f"# Queue = BDP of the higher-RTT path for this config.")
    w(f"**.ppp[*].queue.packetCapacity = {queue_packets_for(rtt_ms)}")
    w(f'*.scenarioManager.script = xmldoc("../scenarios/experiment1/{rtt_ms}ms.xml")')
    w(f'output-vector-file = "results/{config_name}-#0.vec"')
    w(f'output-scalar-file = "results/{config_name}-#0.sca"')
    w()


def main() -> None:
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    for protocol, settings in PROTOCOLS.items():
        out_path = EXPERIMENT_DIR / f"experiment1_{protocol}.ini"
        with out_path.open("w", encoding="utf-8") as f:
            def w(line: str = "") -> None:
                f.write(line + "\n")

            write_common_general(w)
            write_protocol_general(w, protocol, settings)
            for scheduler_title, scheduler_mode in SCHEDULERS:
                for rtt_ms in RTT_SWEEP_MS:
                    write_config(w, settings, scheduler_title, scheduler_mode, rtt_ms)
        print(f"Generated {out_path}.")


if __name__ == "__main__":
    main()

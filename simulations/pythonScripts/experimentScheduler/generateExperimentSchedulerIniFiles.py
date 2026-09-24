#!/usr/bin/env python3

from __future__ import annotations

import math
import random
from pathlib import Path

MSS_BYTES = 1448
PATH_MBPS = 100
PATH_RTT_MS = 20
BACKGROUND_FLOW_COUNT = 5
BACKGROUND_INITIAL_SSTHRESH_BYTES = 40_000
COMPETITION_START_S = 40
COMPETITION_END_S = 80
SIM_TIME_LIMIT_S = 120
RUNS = range(1, 6)
START_RANDOM_SEED = 4999

SCRIPT_DIR = Path(__file__).resolve().parent
SIM_ROOT = SCRIPT_DIR.parents[1]
EXPERIMENT_DIR = SIM_ROOT / "experiments" / "experimentScheduler"


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
        "network = mptcpexperiments.simulations.experiments.experimentScheduler.schedulerResponsiveness",
        f"sim-time-limit = {SIM_TIME_LIMIT_S}s",
        "record-eventlog = false",
        "cmdenv-express-mode = true",
        "cmdenv-event-banners = false",
        "cmdenv-redirect-output = false",
        "cmdenv-output-file = experimentSchedulerLog.txt",
        "cmdenv-log-prefix = %t | %m |",
        "**.cmdenv-log-level = off",
        "",
        f"# Scheduler comparison: two {PATH_MBPS} Mbps paths; RTTs selected per config.",
        f"# Five one-subflow connections using the tested CC join path 2 together at "
        f"{COMPETITION_START_S} s, then stop admitting new data at {COMPETITION_END_S} s.",
        f"# Fixed queue budget from the 20 ms reference BDP: {queue_packets} packets at MSS {MSS_BYTES}.",
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
        "*.scenarioManager.script = xmldoc(\"conditions.xml\")",
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
        "",
        "**.goodputInterval = 0.5s",
        "**.throughputInterval = 0.5s",
        "**.**.tcp.conn-temp.**.statistic-recording = false",
        "**.goodput.statistic-recording = true",
        "**.goodput:vector(removeRepeats).vector-recording = true",
        "**.goodput.result-recording-modes = vector(removeRepeats)",
        "**.throughput.statistic-recording = true",
        "**.throughput:vector(removeRepeats).vector-recording = true",
        "**.throughput.result-recording-modes = vector(removeRepeats)",
        "**.cwnd.statistic-recording = true",
        "**.cwnd:vector(removeRepeats).vector-recording = true",
        "**.cwnd.result-recording-modes = vector(removeRepeats)",
        "**.mbytesInFlight.statistic-recording = true",
        "**.mbytesInFlight:vector(removeRepeats).vector-recording = true",
        "**.mbytesInFlight.result-recording-modes = vector(removeRepeats)",
        "**.retransmissionRate.statistic-recording = true",
        "**.retransmissionRate:vector(removeRepeats).vector-recording = true",
        "**.retransmissionRate.result-recording-modes = vector(removeRepeats)",
        "**.numRtos.statistic-recording = true",
        "**.numRtos:vector(removeRepeats).vector-recording = true",
        "**.numRtos.result-recording-modes = vector(removeRepeats)",
        "**.holBlockedBytes.statistic-recording = true",
        "**.holBlockedBytes:vector(removeRepeats).vector-recording = true",
        "**.holBlockedBytes.result-recording-modes = vector(removeRepeats)",
        "**.subflowSendQueueBytes.statistic-recording = true",
        "**.subflowSendQueueBytes:vector(removeRepeats).vector-recording = true",
        "**.subflowSendQueueBytes.result-recording-modes = vector(removeRepeats)",
        "**.metaReinjectedBytes.statistic-recording = true",
        "**.metaReinjectedBytes:vector(removeRepeats).vector-recording = true",
        "**.metaReinjectedBytes.result-recording-modes = vector(removeRepeats)",
        "**.metaReinjections.statistic-recording = true",
        "**.metaReinjections:vector(removeRepeats).vector-recording = true",
        "**.metaReinjections.result-recording-modes = vector(removeRepeats)",
        "**.mpOrbForwardQueueingDelay.statistic-recording = true",
        "**.mpOrbForwardQueueingDelay:vector(removeRepeats).vector-recording = true",
        "**.mpOrbForwardQueueingDelay.result-recording-modes = vector(removeRepeats)",
        "**.mpOrbReverseQueueingDelay.statistic-recording = true",
        "**.mpOrbReverseQueueingDelay:vector(removeRepeats).vector-recording = true",
        "**.mpOrbReverseQueueingDelay.result-recording-modes = vector(removeRepeats)",
        "**.intSchedulerScore.statistic-recording = true",
        "**.intSchedulerScore:vector(removeRepeats).vector-recording = true",
        "**.intSchedulerScore.result-recording-modes = vector(removeRepeats)",
        "**.intSchedulerBurstBytes.statistic-recording = true",
        "**.intSchedulerBurstBytes:vector(removeRepeats).vector-recording = true",
        "**.intSchedulerBurstBytes.result-recording-modes = vector(removeRepeats)",
        "**.intSchedulerFreshFeedback.statistic-recording = true",
        "**.intSchedulerFreshFeedback:vector(removeRepeats).vector-recording = true",
        "**.intSchedulerFreshFeedback.result-recording-modes = vector(removeRepeats)",
        "**.intSchedulerProbe.statistic-recording = true",
        "**.intSchedulerProbe:vector(removeRepeats).vector-recording = true",
        "**.intSchedulerProbe.result-recording-modes = vector(removeRepeats)",
        "**.queueLength.statistic-recording = true",
        "**.queueLength:vector(removeRepeats).vector-recording = true",
        "**.queueLength.result-recording-modes = vector(removeRepeats)",
        f"**.ppp[*].queue.packetCapacity = {queue_packets}",
        "# Keep these fallbacks after the specific recording rules above.",
        "# To enable additional statistics as vectors, set BOTH statistic-recording",
        "# and vector-recording to true; vector-recording alone cannot enable a disabled statistic.",
        "**.statistic-recording = false",
        "**.scalar-recording = false",
        "**.vector-recording = false",
        "**.bin-recording = false",
        "",
    )
    for line in lines:
        write(line)


PROFILES = {"equal": (20, 20), "reversed": (60, 20)}
SCHEDULERS = ("default", "defaultCwnd", "intInformed")
METRICS = ['goodput', 'throughput', 'cwnd', 'mbytesInFlight', 'retransmissionRate', 'numRtos', 'holBlockedBytes', 'subflowSendQueueBytes', 'metaReinjectedBytes', 'metaReinjections', 'mpOrbForwardQueueingDelay', 'mpOrbReverseQueueingDelay', 'intSchedulerScore', 'intSchedulerBurstBytes', 'intSchedulerFreshFeedback', 'intSchedulerProbe', 'queueLength']


def config_prefix(profile, scheduler):
    return f"Alpha_{profile}_{scheduler}"


def main():
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    write = lambda line="": lines.append(line)
    write_common_general(write)
    write('# Fixed 173-packet queues: one 100 Mbps / 20 ms BDP in both RTT profiles.')
    write('**.tcp.typename = "MpOrb"')
    write('**.tcp.tcpAlgorithmClass = "MpOrbSemiCoupledAlpha"')
    write('*.backgroundClient[*].tcp.conn-*.schedulerMode = "default"')
    write('*.backgroundServer[*].tcp.conn-*.schedulerMode = "default"')
    write('**.p1Ingress.ppp[0].queue.typename = "PintQueue"')
    write('**.p2Ingress.ppp[0].queue.typename = "PintQueue"')
    write('**.ppp[*].queue.typename = "DropTailQueue"')
    write('**.ppp[*].queue.dropperClass = "inet::queueing::PacketAtCollectionEndDropper"')
    write('**.additiveIncreasePercent = 0.05')
    write('**.eta = 0.95')
    write('**.alpha = 0.03')
    write('**.fixedAvgRTTVal = 0s')
    write('**.pintFeedbackProbability = 1')
    write('**.pintSeparateQueueingDelay = true')
    for profile, (rtt1, rtt2) in PROFILES.items():
        for scheduler in SCHEDULERS:
            for run in RUNS:
                config = f"{config_prefix(profile, scheduler)}_Run{run}"
                write()
                write(f'[Config {config}]')
                write(f'description = "MpOrbSemiCoupledAlpha; {scheduler}; RTT {rtt1}/{rtt2} ms; run {run}"')
                write(f'seed-set = {run}')
                write(f'*.path1Rtt = {rtt1}ms')
                write(f'*.path2Rtt = {rtt2}ms')
                write(f'*.client[0].tcp.conn-*.schedulerMode = "{scheduler}"')
                write(f'*.server[0].tcp.conn-*.schedulerMode = "{scheduler}"')
                start = flow_start_time(run)
                write(f'*.client[0].app[0].tOpen = {start:.6f}s')
                write(f'*.client[0].app[0].tSend = {start:.6f}s')
                write('*.backgroundClient[*].app[0].tOpen = 40s')
                write('*.backgroundClient[*].app[0].tSend = 40s')
                write(f'output-vector-file = "results/{config}-#0.vec"')
                write(f'output-scalar-file = "results/{config}-#0.sca"')
    path = EXPERIMENT_DIR / 'experimentScheduler.ini'
    path.write_text("\n".join(lines) + "\n")
    print(f"Generated {path}: {len(PROFILES) * len(SCHEDULERS) * len(RUNS)} configurations, {bdp_packets()} packets per queue")


if __name__ == '__main__':
    main()

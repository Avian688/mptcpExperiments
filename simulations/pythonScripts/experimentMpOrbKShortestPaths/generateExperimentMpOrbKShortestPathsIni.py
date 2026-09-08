#!/usr/bin/env python3
"""Edge-disjoint Alpha K=2..5 and policy-matched OrbCC/PINT K=1."""

import argparse
import json
import random
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SIMULATIONS_DIR = SCRIPT_DIR.parents[1]
SAMPLES_DIR = SIMULATIONS_DIR.parent.parent
EXPERIMENT_DIR = SIMULATIONS_DIR / "experiments" / "experimentMpOrbKShortestPaths"
INI_FILE = EXPERIMENT_DIR / "experimentMpOrbKShortestPaths.ini"
MANIFEST_FILE = EXPERIMENT_DIR / "matrix.json"
sys.path.insert(0, str(SCRIPT_DIR.parent / "experimentKShortestPaths"))
from generateExperimentKShortestPathsIni import (
    CITY_COORDINATES, PAIR_DEFINITIONS, PATH_COUNT, MAX_RTT_SPREAD_MS,
    K_PATH_SNAPSHOT_SET, load_ground_stations, endpoint_pair_specification,
)

RUN_COUNT = 5
PATH_COUNTS = (1, 2, 3, 4, 5)
SIM_TIME = 300
WARMUP = 10
ROUTE_STORE = "../experimentKShortestPaths/leoSaves"


def configurations(sim_time=SIM_TIME):
    # TcpPacedConnection.enqueueData() refills OrbCC and MPTCP meta queues
    # during ACK processing, so sendBytes only primes a persistent workload.
    if not 20 <= sim_time or not sim_time < float("inf"):
        raise ValueError("Simulation time must be finite and at least 20 seconds")
    configs = []
    for group, (pair, source_city, destination_city, source, destination) in enumerate(PAIR_DEFINITIONS):
        for k in PATH_COUNTS:
            protocol = "OrbccPint" if k == 1 else "MpOrbAlpha"
            for run in range(1, RUN_COUNT + 1):
                seed = 4999 + run
                start = round(random.Random(seed).uniform(1, 2), 6)
                configs.append(dict(
                    config=f"{protocol}_{pair}_EdgeDisjoint_K{k}_Run{run}",
                    protocol=protocol, policy="EdgeDisjoint", pair=pair,
                    source_city=source_city, destination_city=destination_city,
                    source=source, destination=destination, path_group=group,
                    k=k, run=run, seed=seed, start=start, sim_time=sim_time,
                    measurement_start=WARMUP, measurement_end=sim_time - 1,
                ))
    return configs


def write_network(f):
    """Preserve the catalog generator's geometry, IDs, and route profile."""
    stations = load_ground_stations()
    f.write('''network = mptcpexperiments.simulations.experiments.experimentKShortestPaths.kshortestpathsping
*.*.ipv4.typename = "LeoIpv4NetworkLayer"
**.ipv4.configurator.typename = "LeoIpv4NodeConfigurator"
*.*.ipv4.arp.typename = "GlobalArp"
*.*.ipv4.routingTable.netmaskRoutes = ""
*.*.forwarding = true
**.constraintAreaMinX = 0m
**.constraintAreaMaxX = 2160m
**.constraintAreaMinY = 0m
**.constraintAreaMaxY = 1080m
**.constraintAreaMinZ = 0m
**.constraintAreaMaxZ = 0m
**.groundStation[*].mobility.typename = "GroundStationMobility"
*.groundStation[*].mobility.initFromDisplayString = false
*.groundStation[*].mobility.updateFromDisplayString = false
**.userTerminal[*].mobility.typename = "GroundStationMobility"
*.userTerminal[*].mobility.initFromDisplayString = false
*.userTerminal[*].mobility.updateFromDisplayString = false
*.configurator.config = xml("<config><interface hosts='**' address='10.x.x.x' netmask='255.x.x.x'/><autoroute metric='delay'/></config>")
*.configurator.addStaticRoutes = true
*.configurator.optimizeRoutes = false
*.configurator.kPathsEdgeDisjoint = true
*.configurator.kPathMaxSharedLinks = -1
*.configurator.kPathSnapshotMode = "load"
*.configurator.kPathPingRouting = true
*.configurator.allowRouteSnapshotOverwrite = false
**.loadFiles = true
**.numOfSats = 1584
**.satsPerPlane = 22
**.numOfPlanes = 72
**.incl = 53
**.alt = 550
**.numOfClients = 0
**.enableInterSatelliteLinks = true
**.satellite[*].NoradModule.satIndex = parentIndex()
**.satellite[*].NoradModule.satName = "Starlink Satellite"
**.satellite[*].NoradModule.inclination = 53*0.0174533
**.satellite[*].NoradModule.altitude = 550
**.satellite[*].mobility.typename = "SatelliteMobility"
**.satellite[*].mobility.updateInterval = 100ms
**.satellite[*].**.bitrate = 100Mbps
**.dataRate = 100Mbps
**.queueSize = 300
**.userTerminalUpdateInterval = 15s
**.userTerminalSampleInterval = 1s
''')
    f.write(f'*.configurator.configLocation = "{ROUTE_STORE}"\n')
    f.write(f'*.configurator.numOfKPaths = {PATH_COUNT}\n')
    f.write(f'*.configurator.kPathMaxRttSpread = {MAX_RTT_SPREAD_MS}ms\n')
    f.write(f'*.configurator.kPathSnapshotSet = "{K_PATH_SNAPSHOT_SET}"\n')
    f.write(f'*.configurator.kPathEndpointPairs = "{endpoint_pair_specification()}"\n')
    f.write(f'**.numOfGS = {len(CITY_COORDINATES) + len(stations)}\n')
    f.write(f'**.numOfUserTerminals = {2 * len(PAIR_DEFINITIONS)}\n')
    locations = [(name, lat, lon) for name, (lat, lon) in CITY_COORDINATES.items()]
    locations.extend((s["Location Comment"], s["Latitude"], s["Longitude"]) for s in stations)
    for index, (city, lat, lon) in enumerate(locations):
        f.write(f'**.groundStation[{index}].cityName = {json.dumps(city)}\n')
        f.write(f'**.groundStation[{index}].mobility.latitude = {lat}\n')
        f.write(f'**.groundStation[{index}].mobility.longitude = {lon}\n')
    for _, source_city, destination_city, source, destination in PAIR_DEFINITIONS:
        for terminal, city in ((source, source_city), (destination, destination_city)):
            lat, lon = CITY_COORDINATES[city]
            f.write(f'*.userTerminal[{terminal}].mobility.latitude = {lat}\n')
            f.write(f'*.userTerminal[{terminal}].mobility.longitude = {lon}\n')


def write_transport(f):
    f.write('''
# Same PINT telemetry and base OrbCC gains on both transports.
**.interfaceType = "orbtcp.linklayer.ppp.PintInterface"
**.ppp[*].queue.typename = "PintQueue"
**.ppp[*].queue.packetCapacity = 300
**.tcp.advertisedWindow = 200000000
**.tcp.windowScalingSupport = true
**.tcp.windowScalingFactor = -1
**.tcp.increasedIWEnabled = true
**.tcp.delayedAcksEnabled = false
**.tcp.timestampSupport = true
**.tcp.ecnWillingness = false
**.tcp.nagleEnabled = true
**.tcp.sackSupport = true
**.tcp.updatedSackEnabled = true
**.tcp.stopOperationTimeout = 4000s
# Leave room for TCP/PINT/MPTCP options without IPv4 fragmentation.
**.tcp.mss = 1200
**.tcp.initialSsthresh = 4800000
**.tcp.sendQueueLimit = 4MiB
**.tcp.subflowInterfaceBinding = false
**.schedulerMode = "default"
**.startAllSubflowsAtBeginning = true
**.subflowStartTimes = ""
**.additiveIncreasePercent = 0.05
**.eta = 0.95
**.alpha = 0.03
**.tcp.pintFeedbackProbability = 1
**.pintFlowCountBits = 8
**.pintMaxFlowCount = 65535
**.pintUseAverageRtt = true
**.tcp.pintUseInitialPhase = true
**.tcp.pintUseInitialPhaseFlowCount = true
**.ppp[*].queue.pintInitialRtt = 10ms
**.ppp[*].queue.flowCountSketchEnabled = true
**.ppp[*].queue.flowCardinalityBits = 4096
**.ppp[*].queue.flowSketchSeed = 1337
**.ppp[*].queue.pintBits = 8
**.ppp[*].queue.pintAutoScaleEncoding = false
**.ppp[*].queue.pintLogBase = 1.05
**.goodputInterval = 1s
**.throughputInterval = 1s
**.ipv4.ip.kPathTcpClientPort = 4000
**.ipv4.ip.kPathTcpServerPort = 1000
''')


def write_recording(f):
    # First matching recording entry wins. Keep actual per-connection modules.
    f.write('**.tcp.conn-temp.**.statistic-recording = false\n')
    metrics = ("goodput", "throughput", "retransmissionRate", "cwnd", "rtt", "srtt",
               "numRtos", "holBlockedBytes", "metaReinjectedBytes",
               "semiCoupledAlphaRateShare", "semiCoupledAlphaSubflowRate",
               "semiCoupledAlphaConnectionRate", "kPathAvailable", "kPathExpectedRtt",
               "kPathCatalogSize")
    for metric in metrics:
        f.write(f'**.{metric}.statistic-recording = true\n')
        f.write(f'**.{metric}.result-recording-modes = vector\n')
        f.write(f'**.{metric}:vector.vector-recording = true\n')
    f.write('''**.app[0].bytesRcvd.scalar-recording = true
**.statistic-recording = false
**.vector-recording = false
**.scalar-recording = false
**.bin-recording = false
''')


def generate_ini(sim_time=SIM_TIME):
    configs = configurations(sim_time)
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)
    with INI_FILE.open("w", encoding="utf-8") as f:
        f.write('# Generated by generateExperimentMpOrbKShortestPathsIni.py\n[General]\n')
        f.write(f'sim-time-limit = {sim_time:g}s\n')
        f.write('record-eventlog = false\ncmdenv-express-mode = true\ncmdenv-event-banners = false\n**.cmdenv-log-level = off\n')
        write_network(f)
        write_transport(f)
        write_recording(f)
        for c in configs:
            k, src, dst = c["k"], c["source"], c["destination"]
            f.write(f'\n[Config {c["config"]}]\n')
            f.write(f'seed-set = {c["seed"]}\n')
            f.write(f'output-vector-file = "results/{c["config"]}-#0.vec"\n')
            f.write(f'output-scalar-file = "results/{c["config"]}-#0.sca"\n')
            f.write(f'**.tcp.typename = "{"Orbtcp" if k == 1 else "MpOrb"}"\n')
            f.write(f'**.tcp.tcpAlgorithmClass = "{"OrbtcpPintFlavour" if k == 1 else "MpOrbSemiCoupledAlpha"}"\n')
            f.write(f'**.numberOfSubflows = {k}\n')
            f.write(f'**.ipv4.ip.kPathTcpPathGroup = {c["path_group"]}\n')
            f.write(f'**.ipv4.ip.kPathTcpSubflows = {k}\n')
            f.write(f'*.userTerminal[{src}].numApps = {k + 1}\n')
            f.write(f'*.userTerminal[{dst}].numApps = 1\n')
            f.write('*.userTerminal[*].numApps = 0\n')
            sender, receiver = f'*.userTerminal[{src}].app[0]', f'*.userTerminal[{dst}].app[0]'
            f.write(f'{sender}.typename = "{"TcpGoodputSessionApp" if k == 1 else "MpTcpSessionApp"}"\n')
            f.write(f'{sender}.localPort = 4000\n{sender}.connectPort = 1000\n')
            f.write(f'{sender}.connectAddress = "userTerminal[{dst}]"\n')
            f.write(f'{sender}.tOpen = {c["start"]}s\n{sender}.tSend = {c["start"]}s\n')
            # A small application write avoids adding another 2 GB to a queue
            # already filled by handshake/ACK processing. Use a positive close
            # time beyond the run: base TcpSessionApp does not honor -1 here.
            f.write(f'{sender}.tClose = {sim_time + 1:g}s\n{sender}.sendBytes = 1MiB\n{sender}.dataTransferMode = "bytecount"\n')
            f.write(f'{receiver}.typename = "{"TcpSinkApp" if k == 1 else "MpTcpSinkApp"}"\n')
            f.write(f'{receiver}.localPort = 1000\n')
            f.write(f'{receiver}.serverThreadModuleType = "tcpgoodputapplications.applications.tcpapp.TcpGoodputSinkAppThread"\n')
            for rank in range(1, k + 1):
                app = f'*.userTerminal[{src}].app[{rank}]'
                f.write(f'{app}.typename = "KShortestPathPingApp"\n')
                f.write(f'{app}.destAddr = "userTerminal[{dst}]"\n')
                f.write(f'{app}.pathGroup = {c["path_group"]}\n{app}.pathIndex = {rank}\n')
                f.write(f'{app}.monitorOnly = true\n{app}.count = -1\n')
                f.write(f'{app}.startTime = 0.000002s\n{app}.stopTime = {sim_time:g}s\n')
                f.write(f'{app}.sendInterval = 100ms\n{app}.printPing = false\n')
    MANIFEST_FILE.write_text(json.dumps(configs, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {len(configs)} configurations: 100 Alpha + 25 OrbCC/PINT; {sim_time:g}s each")
    return configs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim-time", type=float, default=SIM_TIME)
    args = parser.parse_args()
    generate_ini(args.sim_time)

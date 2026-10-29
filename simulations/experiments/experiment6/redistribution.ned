package mptcpexperiments.simulations.experiments.experiment6;
@namespace(inet);
import inet.node.inet.StandardHost;
import inet.node.inet.Router;
import ned.DatarateChannel;
import inet.common.scenario.ScenarioManager;
import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;
network redistribution
{
    parameters:
        double pathRtt @unit(s) = default(20ms);
        double linkCapacity @unit(bps) = default(100Mbps);
    submodules:
        client[5]: StandardHost;
        server[5]: StandardHost;
        router[8]: Router;
        configurator: AutoNetworkConfigurator;
        scenarioManager: ScenarioManager;
    connections:
        router[0].pppg++ <--> DatarateChannel { datarate = parent.linkCapacity; delay = 0s; } <--> router[1].pppg++;
        router[2].pppg++ <--> DatarateChannel { datarate = parent.linkCapacity; delay = 0s; } <--> router[3].pppg++;
        router[4].pppg++ <--> DatarateChannel { datarate = parent.linkCapacity; delay = 0s; } <--> router[5].pppg++;
        router[6].pppg++ <--> DatarateChannel { datarate = parent.linkCapacity; delay = 0s; } <--> router[7].pppg++;
        client[0].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[0].pppg++;
        server[0].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[1].pppg++;
        client[0].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[2].pppg++;
        server[0].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[3].pppg++;
        client[1].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[2].pppg++;
        server[1].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[3].pppg++;
        client[1].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[4].pppg++;
        server[1].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[5].pppg++;
        client[2].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[4].pppg++;
        server[2].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[5].pppg++;
        client[2].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[6].pppg++;
        server[2].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[7].pppg++;
        client[3].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[6].pppg++;
        server[3].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[7].pppg++;
        client[4].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[0].pppg++;
        server[4].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> router[1].pppg++;
}

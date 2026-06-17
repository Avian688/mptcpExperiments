package mptcpexperiments.simulations.experiments.experiment1;
@namespace(inet);

import inet.common.scenario.ScenarioManager;
import inet.node.inet.Router;
import inet.node.inet.StandardHost;
import ned.DatarateChannel;
import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;

network schedulernegativetwopaths
{
    parameters:
        @display("bgb=720,440");
        int numberOfClientServers = default(1);
        double fixedPathRtt @unit(s) = default(20ms);
        double variablePathRtt @unit(s) = default(60ms);
        double fixedPathDatarate @unit(bps) = default(10Mbps);
        double variablePathDatarate @unit(bps) = default(100Mbps);

    submodules:
        client[numberOfClientServers]: StandardHost {
            @display("p=80,100,m,1,numberOfClientServers,100");
        }

        server[numberOfClientServers]: StandardHost {
            @display("p=640,100,m,1,numberOfClientServers,100");
        }

        router1a: Router {
            @display("p=260,110");
        }

        router2a: Router {
            @display("p=460,110");
        }

        router1b: Router {
            @display("p=260,280");
        }

        router2b: Router {
            @display("p=460,280");
        }

        configurator: AutoNetworkConfigurator {
            @display("p=540,380");
        }

        scenarioManager: ScenarioManager {
            @display("p=120,380;is=s");
        }

    connections:
        for i=0..sizeof(client)-1 {
            // Path 0: fixed RTT and bottleneck.
            client[i].pppg++ <--> DatarateChannel { delay = fixedPathRtt / 4; datarate = 10Gbps; } <--> router1a.pppg++;
            router2a.pppg++ <--> DatarateChannel { delay = fixedPathRtt / 4; datarate = 10Gbps; } <--> server[i].pppg++;

            // Path 1: variable RTT and bottleneck.
            client[i].pppg++ <--> DatarateChannel { delay = variablePathRtt / 4; datarate = 10Gbps; } <--> router1b.pppg++;
            router2b.pppg++ <--> DatarateChannel { delay = variablePathRtt / 4; datarate = 10Gbps; } <--> server[i].pppg++;
        }

        router1a.pppg++ <--> DatarateChannel { delay = 0ms; datarate = fixedPathDatarate; } <--> router2a.pppg++;
        router1b.pppg++ <--> DatarateChannel { delay = 0ms; datarate = variablePathDatarate; } <--> router2b.pppg++;
}

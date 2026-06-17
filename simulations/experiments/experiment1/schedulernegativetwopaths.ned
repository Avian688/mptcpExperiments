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

    types:
        channel accessLine60ms extends DatarateChannel
        {
            delay = 15ms;
            datarate = 10Gbps;
        }

        channel bottleneckLine25Mbps extends DatarateChannel
        {
            delay = 0ms;
            datarate = 25Mbps;
        }

        channel accessLine100ms extends DatarateChannel
        {
            delay = 25ms;
            datarate = 10Gbps;
        }

        channel bottleneckLine100Mbps extends DatarateChannel
        {
            delay = 0ms;
            datarate = 100Mbps;
        }

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
            // Path 0: 60 ms RTT, 25 Mbps bottleneck.
            client[i].pppg++ <--> accessLine60ms <--> router1a.pppg++;
            router2a.pppg++ <--> accessLine60ms <--> server[i].pppg++;

            // Path 1: 100 ms RTT, 100 Mbps bottleneck.
            client[i].pppg++ <--> accessLine100ms <--> router1b.pppg++;
            router2b.pppg++ <--> accessLine100ms <--> server[i].pppg++;
        }

        router1a.pppg++ <--> bottleneckLine25Mbps <--> router2a.pppg++;
        router1b.pppg++ <--> bottleneckLine100Mbps <--> router2b.pppg++;
}

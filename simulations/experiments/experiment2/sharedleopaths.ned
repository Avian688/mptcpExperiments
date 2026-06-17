package mptcpexperiments.simulations.experiments.experiment2;
@namespace(inet);

import inet.common.scenario.ScenarioManager;
import inet.node.inet.Router;
import inet.node.inet.StandardHost;
import ned.DatarateChannel;
import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;

network sharedleopaths
{
    parameters:
        @display("bgb=900,620");
        int numberOfClientServers = default(3);

    types:
        channel access60ms extends DatarateChannel
        {
            delay = 15ms;
            datarate = 10Gbps;
        }

        channel access70ms extends DatarateChannel
        {
            delay = 17.5ms;
            datarate = 10Gbps;
        }

        channel access80ms extends DatarateChannel
        {
            delay = 20ms;
            datarate = 10Gbps;
        }

        channel access90ms extends DatarateChannel
        {
            delay = 22.5ms;
            datarate = 10Gbps;
        }

        channel access100ms extends DatarateChannel
        {
            delay = 25ms;
            datarate = 10Gbps;
        }

        channel access110ms extends DatarateChannel
        {
            delay = 27.5ms;
            datarate = 10Gbps;
        }

        channel access120ms extends DatarateChannel
        {
            delay = 30ms;
            datarate = 10Gbps;
        }

        channel access130ms extends DatarateChannel
        {
            delay = 32.5ms;
            datarate = 10Gbps;
        }

        channel bottleneck100Mbps extends DatarateChannel
        {
            delay = 0ms;
            datarate = 100Mbps;
        }

    submodules:
        client[numberOfClientServers]: StandardHost {
            @display("p=80,100,m,1,numberOfClientServers,150");
        }

        server[numberOfClientServers]: StandardHost {
            @display("p=820,100,m,1,numberOfClientServers,150");
        }

        router1[8]: Router {
            @display("p=300,60,m,1,8,65");
        }

        router2[8]: Router {
            @display("p=600,60,m,1,8,65");
        }

        configurator: AutoNetworkConfigurator {
            @display("p=725,560");
        }

        scenarioManager: ScenarioManager {
            @display("p=135,560;is=s");
        }

    connections:
        // User A uses paths 1,2,3,4.
        // User B uses paths 1,2,5,6.
        // User C uses paths 3,4,7,8.
        //
        // Connection order matters: MPTCP assigns subflow N to client/server
        // interface N+1, so each user's interfaces are added in path-list order.

        // Path 1: 60 ms RTT, shared by A and B.
        client[0].pppg++ <--> access60ms <--> router1[0].pppg++;
        router2[0].pppg++ <--> access60ms <--> server[0].pppg++;
        client[1].pppg++ <--> access60ms <--> router1[0].pppg++;
        router2[0].pppg++ <--> access60ms <--> server[1].pppg++;

        // Path 2: 70 ms RTT, shared by A and B.
        client[0].pppg++ <--> access70ms <--> router1[1].pppg++;
        router2[1].pppg++ <--> access70ms <--> server[0].pppg++;
        client[1].pppg++ <--> access70ms <--> router1[1].pppg++;
        router2[1].pppg++ <--> access70ms <--> server[1].pppg++;

        // Path 3: 80 ms RTT, shared by A and C.
        client[0].pppg++ <--> access80ms <--> router1[2].pppg++;
        router2[2].pppg++ <--> access80ms <--> server[0].pppg++;
        client[2].pppg++ <--> access80ms <--> router1[2].pppg++;
        router2[2].pppg++ <--> access80ms <--> server[2].pppg++;

        // Path 4: 90 ms RTT, shared by A and C.
        client[0].pppg++ <--> access90ms <--> router1[3].pppg++;
        router2[3].pppg++ <--> access90ms <--> server[0].pppg++;
        client[2].pppg++ <--> access90ms <--> router1[3].pppg++;
        router2[3].pppg++ <--> access90ms <--> server[2].pppg++;

        // Path 5: 100 ms RTT, used only by B.
        client[1].pppg++ <--> access100ms <--> router1[4].pppg++;
        router2[4].pppg++ <--> access100ms <--> server[1].pppg++;

        // Path 6: 110 ms RTT, used only by B.
        client[1].pppg++ <--> access110ms <--> router1[5].pppg++;
        router2[5].pppg++ <--> access110ms <--> server[1].pppg++;

        // Path 7: 120 ms RTT, used only by C.
        client[2].pppg++ <--> access120ms <--> router1[6].pppg++;
        router2[6].pppg++ <--> access120ms <--> server[2].pppg++;

        // Path 8: 130 ms RTT, used only by C.
        client[2].pppg++ <--> access130ms <--> router1[7].pppg++;
        router2[7].pppg++ <--> access130ms <--> server[2].pppg++;

        router1[0].pppg++ <--> bottleneck100Mbps <--> router2[0].pppg++;
        router1[1].pppg++ <--> bottleneck100Mbps <--> router2[1].pppg++;
        router1[2].pppg++ <--> bottleneck100Mbps <--> router2[2].pppg++;
        router1[3].pppg++ <--> bottleneck100Mbps <--> router2[3].pppg++;
        router1[4].pppg++ <--> bottleneck100Mbps <--> router2[4].pppg++;
        router1[5].pppg++ <--> bottleneck100Mbps <--> router2[5].pppg++;
        router1[6].pppg++ <--> bottleneck100Mbps <--> router2[6].pppg++;
        router1[7].pppg++ <--> bottleneck100Mbps <--> router2[7].pppg++;
}

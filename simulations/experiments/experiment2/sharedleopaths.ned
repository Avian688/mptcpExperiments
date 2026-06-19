package mptcpexperiments.simulations.experiments.experiment2;
@namespace(inet);

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

    connections:
        // A uses paths 1-4, B uses 1,2,5,6, and C uses 3,4,7,8.
        // All paths have identical RTT and capacity so only sharing differs.

        // Paths 1 and 2 are shared by A and B.
        client[0].pppg++ <--> access60ms <--> router1[0].pppg++;
        router2[0].pppg++ <--> access60ms <--> server[0].pppg++;
        client[1].pppg++ <--> access60ms <--> router1[0].pppg++;
        router2[0].pppg++ <--> access60ms <--> server[1].pppg++;

        client[0].pppg++ <--> access60ms <--> router1[1].pppg++;
        router2[1].pppg++ <--> access60ms <--> server[0].pppg++;
        client[1].pppg++ <--> access60ms <--> router1[1].pppg++;
        router2[1].pppg++ <--> access60ms <--> server[1].pppg++;

        // Paths 3 and 4 are shared by A and C.
        client[0].pppg++ <--> access60ms <--> router1[2].pppg++;
        router2[2].pppg++ <--> access60ms <--> server[0].pppg++;
        client[2].pppg++ <--> access60ms <--> router1[2].pppg++;
        router2[2].pppg++ <--> access60ms <--> server[2].pppg++;

        client[0].pppg++ <--> access60ms <--> router1[3].pppg++;
        router2[3].pppg++ <--> access60ms <--> server[0].pppg++;
        client[2].pppg++ <--> access60ms <--> router1[3].pppg++;
        router2[3].pppg++ <--> access60ms <--> server[2].pppg++;

        // B has private paths 5 and 6.
        client[1].pppg++ <--> access60ms <--> router1[4].pppg++;
        router2[4].pppg++ <--> access60ms <--> server[1].pppg++;
        client[1].pppg++ <--> access60ms <--> router1[5].pppg++;
        router2[5].pppg++ <--> access60ms <--> server[1].pppg++;

        // C has private paths 7 and 8.
        client[2].pppg++ <--> access60ms <--> router1[6].pppg++;
        router2[6].pppg++ <--> access60ms <--> server[2].pppg++;
        client[2].pppg++ <--> access60ms <--> router1[7].pppg++;
        router2[7].pppg++ <--> access60ms <--> server[2].pppg++;

        router1[0].pppg++ <--> bottleneck100Mbps <--> router2[0].pppg++;
        router1[1].pppg++ <--> bottleneck100Mbps <--> router2[1].pppg++;
        router1[2].pppg++ <--> bottleneck100Mbps <--> router2[2].pppg++;
        router1[3].pppg++ <--> bottleneck100Mbps <--> router2[3].pppg++;
        router1[4].pppg++ <--> bottleneck100Mbps <--> router2[4].pppg++;
        router1[5].pppg++ <--> bottleneck100Mbps <--> router2[5].pppg++;
        router1[6].pppg++ <--> bottleneck100Mbps <--> router2[6].pppg++;
        router1[7].pppg++ <--> bottleneck100Mbps <--> router2[7].pppg++;
}

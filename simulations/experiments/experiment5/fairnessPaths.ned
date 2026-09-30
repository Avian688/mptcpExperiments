package mptcpexperiments.simulations.experiments.experiment5;
@namespace(inet);
import inet.node.inet.Router;
import inet.node.inet.StandardHost;
import ned.DatarateChannel;
import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;

// A: left -> middle -> right, OR privateIngress -> privateEgress.
// B: left -> middle. C: middle -> right. A's routes are edge-disjoint.
network fairnessPaths
{
    types:
        channel access extends DatarateChannel { datarate = 10Gbps; delay = 5ms; }
        channel sharedLink extends DatarateChannel { datarate = 100Mbps; delay = 0ms; }
    submodules:
        client[3]: StandardHost { @display("p=70,100,column,120"); }
        server[3]: StandardHost { @display("p=850,100,column,120"); }
        left: Router { @display("p=250,150"); }
        middle: Router { @display("p=440,150"); }
        right: Router { @display("p=640,150"); }
        privateIngress: Router { @display("p=250,350"); }
        privateEgress: Router { @display("p=640,350"); }
        configurator: AutoNetworkConfigurator { @display("p=450,480"); }
    connections:
        // Forward PINT queues: left.ppp[0], middle.ppp[1], privateIngress.ppp[0].
        left.pppg++ <--> sharedLink <--> middle.pppg++;
        middle.pppg++ <--> sharedLink <--> right.pppg++;
        privateIngress.pppg++ <--> DatarateChannel { datarate = 20Mbps; delay = 0ms; } <--> privateEgress.pppg++;
        client[0].pppg++ <--> access <--> left.pppg++;
        right.pppg++ <--> access <--> server[0].pppg++;
        client[0].pppg++ <--> access <--> privateIngress.pppg++;
        privateEgress.pppg++ <--> access <--> server[0].pppg++;
        client[1].pppg++ <--> access <--> left.pppg++;
        middle.pppg++ <--> access <--> server[1].pppg++;
        client[2].pppg++ <--> access <--> middle.pppg++;
        right.pppg++ <--> access <--> server[2].pppg++;
}

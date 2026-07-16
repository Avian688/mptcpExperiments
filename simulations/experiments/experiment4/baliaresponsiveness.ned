package mptcpexperiments.simulations.experiments.experiment4;
@namespace(inet);

import inet.common.scenario.ScenarioManager;
import inet.node.inet.Router;
import inet.node.inet.StandardHost;
import ned.DatarateChannel;
import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;

// Two equal MPTCP paths. Temporary one-subflow connections suppress the
// second subflow, creating the small-window recovery case that motivated BALIA.
network baliaresponsiveness
{
    parameters:
        @display("bgb=900,620");

    submodules:
        client[1]: StandardHost {
            @display("p=70,120");
        }

        server[1]: StandardHost {
            @display("p=690,120");
        }

        backgroundClient[5]: StandardHost {
            @display("p=70,330,row,100");
        }

        backgroundServer[5]: StandardHost {
            @display("p=830,330,row,100");
        }

        p1Ingress: Router {
            @display("p=260,100");
        }

        p1Egress: Router {
            @display("p=500,100");
        }

        p2Ingress: Router {
            @display("p=260,290");
        }

        p2Egress: Router {
            @display("p=500,290");
        }

        configurator: AutoNetworkConfigurator {
            @display("p=790,560");
        }

        scenarioManager: ScenarioManager {
            @display("p=110,560;is=s");
        }

    connections:
        // Declare bottlenecks first so their queues are always ppp[0].
        p1Ingress.pppg++ <--> DatarateChannel { delay = 0ms; datarate = 20Mbps; } <--> p1Egress.pppg++;
        p2Ingress.pppg++ <--> DatarateChannel { delay = 0ms; datarate = 20Mbps; } <--> p2Egress.pppg++;

        // Two 5 ms access legs in each direction give each path a 20 ms RTT.
        client[0].pppg++ <--> DatarateChannel { delay = 5ms; datarate = 10Gbps; } <--> p1Ingress.pppg++;
        p1Egress.pppg++ <--> DatarateChannel { delay = 5ms; datarate = 10Gbps; } <--> server[0].pppg++;

        client[0].pppg++ <--> DatarateChannel { delay = 5ms; datarate = 10Gbps; } <--> p2Ingress.pppg++;
        p2Egress.pppg++ <--> DatarateChannel { delay = 5ms; datarate = 10Gbps; } <--> server[0].pppg++;

        // The competing connections have no route through path 1.
        for i=0..sizeof(backgroundClient)-1 {
            backgroundClient[i].pppg++ <--> DatarateChannel { delay = 5ms; datarate = 10Gbps; } <--> p2Ingress.pppg++;
            p2Egress.pppg++ <--> DatarateChannel { delay = 5ms; datarate = 10Gbps; } <--> backgroundServer[i].pppg++;
        }
}

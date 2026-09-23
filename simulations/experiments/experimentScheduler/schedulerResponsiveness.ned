package mptcpexperiments.simulations.experiments.experimentScheduler;
@namespace(inet);

import inet.common.scenario.ScenarioManager;
import inet.node.inet.Router;
import inet.node.inet.StandardHost;
import ned.DatarateChannel;
import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;

// Experiment 4 topology with independently configurable path propagation RTTs.
network schedulerResponsiveness
{
    parameters:
        double path1Rtt @unit(s) = default(20ms);
        double path2Rtt @unit(s) = default(20ms);
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
        p1Ingress.pppg++ <--> DatarateChannel { delay = 0ms; datarate = 100Mbps; } <--> p1Egress.pppg++;
        p2Ingress.pppg++ <--> DatarateChannel { delay = 0ms; datarate = 100Mbps; } <--> p2Egress.pppg++;

        // Four access-leg traversals per RTT; background RTT matches path 2.
        client[0].pppg++ <--> DatarateChannel { delay = path1Rtt / 4; datarate = 10Gbps; } <--> p1Ingress.pppg++;
        p1Egress.pppg++ <--> DatarateChannel { delay = path1Rtt / 4; datarate = 10Gbps; } <--> server[0].pppg++;

        client[0].pppg++ <--> DatarateChannel { delay = path2Rtt / 4; datarate = 10Gbps; } <--> p2Ingress.pppg++;
        p2Egress.pppg++ <--> DatarateChannel { delay = path2Rtt / 4; datarate = 10Gbps; } <--> server[0].pppg++;

        // The competing connections have no route through path 1.
        for i=0..sizeof(backgroundClient)-1 {
            backgroundClient[i].pppg++ <--> DatarateChannel { delay = path2Rtt / 4; datarate = 10Gbps; } <--> p2Ingress.pppg++;
            p2Egress.pppg++ <--> DatarateChannel { delay = path2Rtt / 4; datarate = 10Gbps; } <--> backgroundServer[i].pppg++;
        }
}

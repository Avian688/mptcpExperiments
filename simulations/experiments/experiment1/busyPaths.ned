package mptcpexperiments.simulations.experiments.experiment1;
@namespace(inet);
import inet.common.scenario.ScenarioManager;
import inet.node.inet.Router;
import inet.node.inet.StandardHost;
import ned.DatarateChannel;
import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;

// A uses both paths; B only path 1; C and four temporary connections only path 2.
network busyPaths
{
    parameters:
        double path1Rtt @unit(s) = default(20ms);
        double path2Rtt @unit(s) = default(20ms);
        @display("bgb=900,600");
    submodules:
        client[7]: StandardHost { @display("p=70,60,column,70"); }
        server[7]: StandardHost { @display("p=800,60,column,70"); }
        p1Ingress: Router { @display("p=270,100"); }
        p1Egress: Router { @display("p=580,100"); }
        p2Ingress: Router { @display("p=270,340"); }
        p2Egress: Router { @display("p=580,340"); }
        configurator: AutoNetworkConfigurator { @display("p=400,540"); }
        scenarioManager: ScenarioManager { @display("p=500,540"); }
    connections:
        // Bottleneck forward interfaces are ppp[0], regardless of host count.
        p1Ingress.pppg++ <--> DatarateChannel { datarate = 100Mbps; delay = 0ms; } <--> p1Egress.pppg++;
        p2Ingress.pppg++ <--> DatarateChannel { datarate = 100Mbps; delay = 0ms; } <--> p2Egress.pppg++;
        for i=0..1 {
            client[i].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.path1Rtt / 4; } <--> p1Ingress.pppg++;
            p1Egress.pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.path1Rtt / 4; } <--> server[i].pppg++;
        }
        client[0].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.path2Rtt / 4; } <--> p2Ingress.pppg++;
        p2Egress.pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.path2Rtt / 4; } <--> server[0].pppg++;
        for i=2..6 {
            client[i].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.path2Rtt / 4; } <--> p2Ingress.pppg++;
            p2Egress.pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.path2Rtt / 4; } <--> server[i].pppg++;
        }
}

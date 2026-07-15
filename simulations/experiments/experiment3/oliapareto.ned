package mptcpexperiments.simulations.experiments.experiment3;
@namespace(inet);

import inet.node.inet.Router;
import inet.node.inet.StandardHost;
import ned.DatarateChannel;
import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;

// Minimal all-MPTCP version of the OLIA non-Pareto scenario.
// Blue: x1 uses X, x2 uses T. Red: y1 uses X then T, y2 uses T.
network oliapareto
{
    parameters:
        @display("bgb=1050,650");

    types:
        channel bottleneckX extends DatarateChannel
        {
            delay = 0ms;
            datarate = 90Mbps;
        }

        channel bottleneckT extends DatarateChannel
        {
            delay = 0ms;
            datarate = 120Mbps;
        }

        channel fast0ms extends DatarateChannel
        {
            delay = 0ms;
            datarate = 10Gbps;
        }

        channel delay10ms extends DatarateChannel
        {
            delay = 10ms;
            datarate = 10Gbps;
        }

        channel delay20ms extends DatarateChannel
        {
            delay = 20ms;
            datarate = 10Gbps;
        }

        channel delay25ms extends DatarateChannel
        {
            delay = 25ms;
            datarate = 10Gbps;
        }

        channel delay30ms extends DatarateChannel
        {
            delay = 30ms;
            datarate = 10Gbps;
        }

    submodules:
        client[2]: StandardHost {
            @display("p=70,150,m,1,2,320");
        }

        server[2]: StandardHost {
            @display("p=980,150,m,1,2,320");
        }

        xIngress: Router {
            @display("p=270,160");
        }

        xEgress: Router {
            @display("p=440,160");
        }

        tIngress: Router {
            @display("p=500,450");
        }

        tEgress: Router {
            @display("p=670,450");
        }

        blueXExit: Router {
            @display("p=760,80");
        }

        blueTExit: Router {
            @display("p=800,240");
        }

        redXExit: Router {
            @display("p=800,430");
        }

        redTExit: Router {
            @display("p=800,570");
        }

        configurator: AutoNetworkConfigurator {
            @display("p=960,610");
        }

    connections:
        // Keep the forward bottlenecks at ppp[0] for deterministic queue overrides.
        xIngress.pppg++ <--> bottleneckX <--> xEgress.pppg++;
        tIngress.pppg++ <--> bottleneckT <--> tEgress.pppg++;

        // Red y1 consumes both X and T. This serial path is the inefficient route.
        xEgress.pppg++ <--> delay20ms <--> tIngress.pppg++;

        // Blue x1 through X and x2 through T, both with 100 ms base RTT.
        client[0].pppg++ <--> delay25ms <--> xIngress.pppg++;
        client[0].pppg++ <--> delay25ms <--> tIngress.pppg++;
        xEgress.pppg++ <--> fast0ms <--> blueXExit.pppg++;
        blueXExit.pppg++ <--> delay25ms <--> server[0].pppg++;
        tEgress.pppg++ <--> fast0ms <--> blueTExit.pppg++;
        blueTExit.pppg++ <--> delay25ms <--> server[0].pppg++;

        // Red y1 through X then T and y2 through T, both with 100 ms base RTT.
        client[1].pppg++ <--> delay10ms <--> xIngress.pppg++;
        client[1].pppg++ <--> delay30ms <--> tIngress.pppg++;
        tEgress.pppg++ <--> fast0ms <--> redXExit.pppg++;
        redXExit.pppg++ <--> delay20ms <--> server[1].pppg++;
        tEgress.pppg++ <--> fast0ms <--> redTExit.pppg++;
        redTExit.pppg++ <--> delay20ms <--> server[1].pppg++;
}

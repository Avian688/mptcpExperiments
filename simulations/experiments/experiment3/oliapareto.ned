package mptcpexperiments.simulations.experiments.experiment3;
@namespace(inet);

import inet.node.inet.Router;
import inet.node.inet.StandardHost;
import ned.DatarateChannel;
import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;

// Small all-MPTCP version of the OLIA paper's Scenario B.
// Blue: x1 uses X, x2 uses T. Red: y1 uses X then T, y2 uses T.
network oliapareto
{
    parameters:
        int usersPerType = default(4);
        @display("bgb=1050,650");

    types:
        channel bottleneckX extends DatarateChannel
        {
            delay = 0ms;
            datarate = 27Mbps;
        }

        channel bottleneckT extends DatarateChannel
        {
            delay = 0ms;
            datarate = 36Mbps;
        }

        channel fast0ms extends DatarateChannel
        {
            delay = 0ms;
            datarate = 10Gbps;
        }

        channel delay5ms extends DatarateChannel
        {
            delay = 5ms;
            datarate = 10Gbps;
        }

        channel delay10ms extends DatarateChannel
        {
            delay = 10ms;
            datarate = 10Gbps;
        }

        channel delay12_5ms extends DatarateChannel
        {
            delay = 12.5ms;
            datarate = 10Gbps;
        }

        channel delay15ms extends DatarateChannel
        {
            delay = 15ms;
            datarate = 10Gbps;
        }

    submodules:
        client[2 * usersPerType]: StandardHost {
            @display("p=70,150,m,1,2,320");
        }

        server[2 * usersPerType]: StandardHost {
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
        xEgress.pppg++ <--> delay10ms <--> tIngress.pppg++;

        // Blue x1 through X and x2 through T, both with 50 ms base RTT.
        xEgress.pppg++ <--> fast0ms <--> blueXExit.pppg++;
        tEgress.pppg++ <--> fast0ms <--> blueTExit.pppg++;
        for i=0..usersPerType-1 {
            client[i].pppg++ <--> delay12_5ms <--> xIngress.pppg++;
            client[i].pppg++ <--> delay12_5ms <--> tIngress.pppg++;
            blueXExit.pppg++ <--> delay12_5ms <--> server[i].pppg++;
            blueTExit.pppg++ <--> delay12_5ms <--> server[i].pppg++;
        }

        // Red y2 is slot 0; inefficient y1 is slot 1 and can join later.
        // Both paths retain a 50 ms base RTT.
        tEgress.pppg++ <--> fast0ms <--> redXExit.pppg++;
        tEgress.pppg++ <--> fast0ms <--> redTExit.pppg++;
        for i=0..usersPerType-1 {
            client[usersPerType + i].pppg++ <--> delay15ms <--> tIngress.pppg++;
            client[usersPerType + i].pppg++ <--> delay5ms <--> xIngress.pppg++;
            redTExit.pppg++ <--> delay10ms <--> server[usersPerType + i].pppg++;
            redXExit.pppg++ <--> delay10ms <--> server[usersPerType + i].pppg++;
        }
}

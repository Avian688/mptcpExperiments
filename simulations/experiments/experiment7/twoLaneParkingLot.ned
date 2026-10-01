package mptcpexperiments.simulations.experiments.experiment7;
@namespace(inet);
import inet.node.inet.StandardHost;
import inet.node.inet.Router;
import ned.DatarateChannel;
import tcppaced.networklayer.configurator.ipv4.AutoNetworkConfigurator;

// Each connection has one subflow per lane. The spine crosses all three
// bottlenecks; rib i crosses only bottleneck i. No links join the two lanes.
network twoLaneParkingLot
{
    parameters:
        double pathRtt @unit(s) = default(20ms);
        double linkCapacity @unit(bps) = default(100Mbps);
        @display("bgb=1000,650");
    submodules:
        spineClient: StandardHost { @display("p=60,300"); }
        spineServer: StandardHost { @display("p=930,300"); }
        ribClient[3]: StandardHost { @display("p=250,70,row,220"); }
        ribServer[3]: StandardHost { @display("p=400,540,row,220"); }
        lane0Router[4]: Router { @display("p=170,220,row,220"); }
        lane1Router[4]: Router { @display("p=170,400,row,220"); }
        configurator: AutoNetworkConfigurator { @display("p=80,600"); }
    connections:
        // Allocate core gates before access gates: forward queues are
        // router[0].ppp[0], router[1].ppp[1], router[2].ppp[1] in each lane.
        for i=0..2 {
            lane0Router[i].pppg++ <--> DatarateChannel { datarate = parent.linkCapacity; delay = 0ms; } <--> lane0Router[i+1].pppg++;
            lane1Router[i].pppg++ <--> DatarateChannel { datarate = parent.linkCapacity; delay = 0ms; } <--> lane1Router[i+1].pppg++;
        }
        // Every host's ppp0 belongs to lane 0 and ppp1 belongs to lane 1.
        // Each route has two access legs, each with one-way delay RTT/4.
        spineClient.pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> lane0Router[0].pppg++;
        spineClient.pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> lane1Router[0].pppg++;
        spineServer.pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> lane0Router[3].pppg++;
        spineServer.pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> lane1Router[3].pppg++;
        for i=0..2 {
            ribClient[i].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> lane0Router[i].pppg++;
            ribClient[i].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> lane1Router[i].pppg++;
            ribServer[i].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> lane0Router[i+1].pppg++;
            ribServer[i].pppg++ <--> DatarateChannel { datarate = 10Gbps; delay = parent.pathRtt / 4; } <--> lane1Router[i+1].pppg++;
        }
}

# LEO transport experiments 8, 9, and 10

The comparisons are **OrbCC uncoupled, Alpha, Omega, and CUBIC uncoupled**, in
that order. Every connection in a run uses the selected controller, including
one-subflow background connections. No congestion-control implementation changes
are needed. All use `defaultCwnd` and start all requested subflows at the beginning.

| Experiment | Active traffic in one simulation |
| --- | --- |
| 8 | One connection with K = 1, 2, 3, 4, or 5 requested subflows. |
| 9 | Two competing connections, each with the same requested K. |
| 10 | Experiment 9 plus five one-subflow background connections using ordinary shortest paths. |

Each experiment has 300 configurations: four controllers × three city pairs ×
five K values × five paired seeds. Each lasts 300 s; the measurement window is
[10 s, 299 s]. Starts are independently drawn in [1 s, 2 s] per connection,
with the same draws across controllers, K values, and experiments. Traffic is
persistent: a 1 MiB application write primes the existing transport queue refill;
applications close after the simulation horizon.

The city pairs are London → New York, San Diego → Shanghai, and the shorter
San Diego → Seattle route. One city pair is
active in each simulation. Each connection has **separate source and destination
terminals**, colocated at those cities, matching the arrangement in OrbTCP
experiment 9. Terminals have independent 100 Mbps access links directly to
serving satellites; they are not clients sharing one ground-station access link.
The five backgrounds use the same source and destination cities as the main connections.

The main connections use increasing-RTT ranks from an **edge-disjoint core-path
catalog**. Disjointness excludes terminal access links. `numOfKPaths=10` stays
fixed: K selects a prefix of the same catalog. The first ranked path of the
minimum-cost disjoint set need not be the unrestricted shortest path. Backgrounds
use ordinary primary shortest-path forwarding; they are not forced onto catalog
rank 1. Co-located terminals should select matching serving satellites under the
deterministic selection rule, but delivery still depends on their access state.
The unrestricted shortest path can overlap several paths of the disjoint set.

K remains the **requested** subflow count when fewer paths exist. No ranks are
duplicated, and unavailable ranks drop packets. Monitor-only applications sample
each requested rank every 100 ms without transmitting probes. Summaries report
mean available ranks and the fraction of time all requested ranks are available.
Availability describes the catalog, not completed TCP handshakes. Existing
transport behavior applies: failed/closed subflows are not automatically recreated;
an established subflow can recover when its rank becomes usable again.

All satellite/core/access links retain 100 Mbps and 300-packet queues. OrbCC uses
the existing PINT gains/encoding. Omega applies the existing 5% shuffle coefficient
at physical queues, including access queues; it is not a fixed total sender budget.
MSS is 1200 bytes for the TCP/PINT/MPTCP options. Per-connection access capacity
can limit aggregate goodput even when multiple core paths are available. This
experiment measures path diversity, recovery, and competition under that model.

## Saved routes

Each simulation creates only its active terminals: two in experiment 8, four
in experiment 9, and fourteen in experiment 10. The first main pair uses UT0/1;
the second uses UT2/3; backgrounds use UT4–13. The selected city coordinates are
assigned per configuration. Main endpoint pairs select saved core paths using
their current satellite/ground-station attachments. Adding or renumbering
terminals does not require another saved catalog.

The store is the existing `experimentKShortestPaths/leoSaves`. **The original
primary-route snapshots can be reused** if they cover the selected duration and
match the existing 1584-satellite/100-ground-station ISL core. Primary snapshots
describe that core, so adding terminal pairs does not require new primary routes.
The K-path store is also the **original, unchanged** `ExperimentKShortestPaths`
edge-disjoint five-pair profile. `kPathCoreSnapshotProfile` opts into reusing its
core sequences. The loader validates the original files, core dimensions, path
policy, sequence, checksum, and primary-route hash. It then matches each current
attachment pair to a saved core pair, reverses paths when necessary, and replaces
the old terminal ends in memory. Expected RTT uses the saved core delay plus the
current access delays. Multiple colocated terminal pairs share the saved core
ranks while retaining their own access links. No routing binaries are converted
or rewritten.

The in-memory terminal extensions refresh on routing updates and attachment
changes. A detached terminal or a core pair absent from the current saved snapshot
has no available ranks; there is no shortest-path fallback, path duplication, or
on-demand path computation. This reuse covers attachment pairs present in the
original corpus; it does not turn the five-pair corpus into an all-pairs catalog.
The original strict endpoint-specific loading remains the default when
`kPathCoreSnapshotProfile` is empty.

At setup, the local `leoSaves` folder contained no `.bin` files. Restore the existing
original saves, or generate that original corpus if absent, before transport runs. Commands below
are run from `/Users/av288/omnetpp-6.4.0` using rebuilt libraries in the normal
OMNeT++ environment. The runners do not build libraries. Rebuild `leosatellites`
for core-path reuse and the multiple-group TCP selector before running these
experiments. The scripts never regenerate routes implicitly.

```sh
# Generate INIs/manifests and inspect one seed; no simulation.
.venv/bin/python samples/mptcpExperiments/simulations/pythonScripts/experiment8/runExperiment8.py --dry-run --runs 1

# Only if the original saves are absent: generate the original corpus once.
.venv/bin/python samples/mptcpExperiments/simulations/pythonScripts/experimentKShortestPaths/runExperimentKShortestPathsSaveFiles.py --policies EdgeDisjoint --sim-time 300 --cores 1

# Check every expected timestamp in both stores without simulating.
.venv/bin/python samples/mptcpExperiments/simulations/pythonScripts/experiment8/runExperiment8.py --check-routes --skip-generate

# Run one configuration first; then choose a wider batch.
.venv/bin/python samples/mptcpExperiments/simulations/pythonScripts/experiment9/runExperiment9.py --configs Alpha_SanDiegoToSeattle_K2_Run1 --end-step 1 --cores 1
.venv/bin/python samples/mptcpExperiments/simulations/pythonScripts/experiment10/runExperiment10.py --protocols OrbUncoupled Alpha Omega CubicUncoupled --cores 10
```

Steps are 1=simulate, 2=export, 3=extract, 4=plot. `--start-step`, `--end-step`,
`--runs`, `--configs`, and `--protocols` restrict processing. `--skip-generate`
retains manual INI edits. Successful runs resume only with matching configuration,
output metadata, INI, route inventory, and library metadata. `--rerun` forces a
repeat; `--keep-completed` explicitly retains earlier-build results and provenance.
The original route generator preserves the existing overwrite protection. Saved
snapshots must cover the selected transport duration. Experiments 8–10 need no
terminal-specific save generation.

## Outputs and validation

Each experiment has separate `results/`, `csvs/raw/`, and `csvs/extracted/` folders.
Each extracted run has per-connection `connections.csv`, per-rank `paths.csv`,
`timeseries.csv`, and `summary.json`; diagnostic vector files retain their original
connection/thread IDs. `csvs/summary.csv` covers selected runs. Application goodput
comes from receiver threads and byte counters, so retransmissions and subflow
throughput are not counted twice. A missing receiver scalar is an extraction error,
not zero goodput. A late first goodput sample leaves the steady-window mean missing.
Jain fairness is computed over connection goodputs; all-zero traffic is undefined.

`simulations/plots/experimentN/` contains PNG/PDF comparisons for each selected
city pair and `plot_data.csv` with sample counts and mean/sample standard deviation.
Plots compare main-connection mean goodput, fairness between the two main
connections, available ranks, and aggregate background goodput. Experiment 8's
single-connection fairness is trivially one for positive goodput. Missing runs
remain missing. Detailed traces support recovery and HoL inspection.

Synthetic tests and config/NED/C++ checks do not establish runtime correctness or
controller performance. No route-generation or transport simulations were run
while preparing this setup.

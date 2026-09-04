# K-Shortest Path RTT Experiment

This experiment reuses the five ISL user-terminal pairs from Experiment 9 and
compares these path-selection policies:

- unrestricted K-shortest paths;
- at most 1, 2, 3, 4, or 5 shared undirected core links between any two paths;
- strictly edge-disjoint core paths.

The Experiment 9 bent-pipe modes are intentionally excluded because they do not
offer a multi-hop ISL core over which edge overlap can be varied.

Here, a shared link is a physical link in the routed satellite/ground-station
core. The user-terminal access links at the two endpoints are excluded. This is
a link-overlap constraint, not a count of shared nodes.

The overlap-limited policies greedily retain qualifying paths from the first
256 Yen candidates. They return up to ten paths rather than searching without
limit until ten are found. The strict edge-disjoint policy uses the exact
minimum-cost maximum-flow solver. Results therefore compare the implemented
selection policies, rather than two identical optimizers with one flag changed.

Each policy allows up to ten paths. One `KShortestPathPingApp` instance is
assigned to every pair and path rank, so one policy run measures all 50
pair/rank combinations at one ping every 50 ms per path. The ICMP request and
reply use the same path selector in
opposite directions. Each hop resolves that rank against the currently loaded
snapshot, so a topology update while a ping is in flight can make it unavailable;
it is then counted as a failed ping instead of falling back to the ordinary
shortest route. Pings stop two seconds before the simulation limit so late
replies are not misclassified by shutdown.

Ten paths is a maximum, not a required result. The overlap-limited heuristic
returns every qualifying path found within its 256-candidate budget, capped at
ten. A missing rank therefore means it was not found within that bounded
search, not that global infeasibility was proven. The strict solver returns only
the feasible edge-disjoint paths, often fewer than ten because
endpoint-adjacent core degree is a hard bound. Unavailable ranks remain visible
in the availability and ping-success results.

## Save Routing Files

The dedicated saver first generates ordinary shortest-path routing snapshots,
then loads those files to generate all K-path policy catalogs:

```sh
python3 runExperimentKShortestPathsSaveFiles.py
```

Both layers are kept inside this MPTCP experiment under `leoSaves/`. Nothing
is read from or written to `orbtcpExperiments`; Experiment 9 supplies only the
five city-pair choices.

The saver generates all seven K-path policies by default: unrestricted,
Shared1 through Shared5, and strict edge-disjoint. Use `--policies` to generate
only a subset. Step 1 is the primary shortest-route corpus and step 2 is the
K-path corpus, so `--start-step 2` reuses existing primary files.

After saving the routes, run the ping and analysis stages:

```sh
python3 runExperimentKShortestPaths.py --start-step 2
```

The normal experiment runner performs INI generation, ping simulation, and
analysis as separate steps. Generate the reusable route files first with the
dedicated saver.

The local primary-route corpus must cover the full requested simulation
duration. A shorter corpus requires either regenerating it or passing a
matching shorter `--sim-time`.

The runner steps are: generate the INI, run the seven ping configurations, then
export and plot. Resume at a particular stage with `--start-step N`; for
example, `--start-step 2` reruns only ping and analysis.
The default duration is the Experiment 9 duration of 300 seconds and can be
changed consistently with `--sim-time` when generating a fresh INI/corpus.

Main outputs are `csvs/summary.csv`, the per-sample CSV files, and
`simulations/plots/experimentKShortestPaths/experimentKShortestPaths.pdf`.

## 3D Path Viewer

The companion viewer displays the Earth, the 1,584-satellite constellation,
all ground stations and user terminals, and the ranked paths from the saved
catalogs. It is display-only: it does not construct interfaces, queues, routing
tables, channels, or ping applications. One timer reads the current saved
snapshot and refreshes the batched geometry once per simulated second.

From `simulations/pythonScripts/experimentKShortestPaths`, open a policy and
endpoint pair with:

```sh
python3 runKShortestPathsVisualization.py --policy Shared1 --pair SanDiegoToShanghai
```

The pair can also be selected by number from 1 to 5. Valid policies are
`Unrestricted`, `Shared1` through `Shared5`, and `EdgeDisjoint`. For example:

```sh
python3 runKShortestPathsVisualization.py --policy EdgeDisjoint --pair 4
```

The launcher regenerates the visualization INI by default; pass
`--skip-generate` to retain the existing file. It opens Qtenv using
`visualizeKShortestPaths.ini`. The source endpoint is shown in green, the
destination in red, and the HUD maps each route color to its rank, RTT, and
link count. Unavailable ranks remain listed rather than being silently replaced
by another route. Satellites are pale grey, ground stations are cyan, and user
terminals are amber; only links belonging to the selected ten paths are drawn,
so the full constellation does not become an unreadable mesh.

The viewer reuses `osg-satellites/earth.jpg` on a lightweight OSG globe and
requires OMNeT++ to be built with `WITH_OSG=yes`; osgEarth is not required.
Generate the selected policy's route catalog before opening it. The visualizer
reports the exact expected profile directory if that catalog is absent.

## Non-Edge-Disjoint Default

The configurator itself defaults to `kPathMaxSharedLinks = -1`, meaning ordinary
non-edge-disjoint Yen paths have no overlap limit. It does **not** default to
five shared paths or five shared links.

This experiment sets every policy explicitly. `Shared5` means that each pair of
selected paths may share at most five undirected core links. It does not mean
five paths, and it does not count shared nodes. Strict `EdgeDisjoint` uses the
separate exact solver and shares zero core links.

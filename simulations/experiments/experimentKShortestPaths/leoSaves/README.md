# Local LEO Routing Saves

The route-saving script stores this MPTCP experiment's generated primary and
K-path snapshot corpora here. Generated contents are ignored by Git.

`runExperimentKShortestPathsSaveFiles.py --topology ISL` writes constellation
directories ending in `_ISL`. `--topology GroundRelay` disables inter-satellite
links and writes independent primary and K-path corpora under `_BP`.
The visualization launcher accepts the same topology option to load those files.

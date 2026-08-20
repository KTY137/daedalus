# K-matrix report: sensorlab (higher-twin-nc-v1, spec rev 2)

Runs: 38  |  sham is behavioral null: True

| pair | composable AB/BA | footprint | class | anomaly |
|---|---|---|---|---|
| rename+scale | n/y | conflict | noncomposable-asym | - |
| rename+clip | n/y | conflict | noncomposable-asym | - |
| rename+add | y/y | disjoint | commute-tree | - |
| rename+tighten | y/y | disjoint | commute-tree | - |
| rename+regen | y/y | conflict | commute-tree | - |
| scale+clip | y/y | conflict | noncommute-behavior | - |
| scale+add | y/y | disjoint | commute-tree | - |
| scale+tighten | y/y | disjoint | commute-tree | - |
| scale+regen | y/y | conflict | commute-tree | - |
| clip+add | y/y | disjoint | commute-tree | - |
| clip+tighten | y/y | disjoint | commute-tree | - |
| clip+regen | y/y | conflict | commute-tree | - |
| add+tighten | y/y | disjoint | commute-tree | - |
| add+regen | y/y | conflict | commute-tree | - |
| tighten+regen | y/y | conflict | commute-tree | - |

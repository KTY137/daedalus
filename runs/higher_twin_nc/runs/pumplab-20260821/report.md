# K-matrix report: pumplab (higher-twin-nc-v1, spec rev 2)

Runs: 38  |  sham is behavioral null: True

| pair | composable AB/BA | footprint | class | k_value | anomaly |
|---|---|---|---|---|---|
| rename+scale | n/y | conflict | noncomposable-asym | - | - |
| rename+clip | n/y | conflict | noncomposable-asym | - | - |
| rename+add | y/y | conflict | commute-tree | 0.000000 | - |
| rename+tighten | y/y | disjoint | commute-tree | 0.000000 | - |
| rename+regen | y/y | conflict | commute-tree | 0.000000 | - |
| scale+clip | y/y | conflict | noncommute-behavior | 0.175422 | - |
| scale+add | y/y | disjoint | commute-tree | 0.000000 | - |
| scale+tighten | y/y | disjoint | commute-tree | 0.000000 | - |
| scale+regen | y/y | conflict | commute-tree | 0.000000 | - |
| clip+add | y/y | disjoint | commute-tree | 0.000000 | - |
| clip+tighten | y/y | disjoint | commute-tree | 0.000000 | - |
| clip+regen | y/y | conflict | commute-tree | 0.000000 | - |
| add+tighten | y/y | disjoint | commute-tree | 0.000000 | - |
| add+regen | y/y | conflict | commute-tree | 0.000000 | - |
| tighten+regen | y/y | conflict | commute-tree | 0.000000 | - |

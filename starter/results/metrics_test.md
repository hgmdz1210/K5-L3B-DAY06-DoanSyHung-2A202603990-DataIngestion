| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Filter compliance (n/N) | Chunk count | Build time (s) | Build tokens | Build cost (USD, est.) |
|---|---|---|---|---|---|---|---|---|
| A | test | 1/6 | 2/6 | 0/2 | 1667 | 20.9 | 164,892 | 0.003298 |
| B | test | 3/6 | 5/6 | 0/2 | 879 | 8.61 | 150,668 | 0.003013 |
| C | test | 4/6 | 5/6 | 2/2 (filter applied) | 879 | 0 (reuses B index) | 0 | 0 |

## 2024-03-24 - [O(V+E) optimization for DAG sorting]
**Learning:** In the JAMES ExecutionGraph engine (`james/dag.py`), calling `_validate_no_cycles()` followed by `topological_sort()` performs Kahn's algorithm twice over the entire graph. Since `topological_sort` naturally validates cycles (by checking if the returned order length matches the number of nodes), `_validate_no_cycles` can simply delegate to it.
**Action:** When validating DAG cycles in the future, avoid redundant graph traversals. Use the result of `topological_sort` to confirm if a cycle exists (O(V+E) instead of 2 * O(V+E)).

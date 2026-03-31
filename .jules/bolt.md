## 2024-03-24 - [O(V+E) optimization for DAG sorting]
**Learning:** In the JAMES ExecutionGraph engine (`james/dag.py`), calling `_validate_no_cycles()` followed by `topological_sort()` performs Kahn's algorithm twice over the entire graph. Since `topological_sort` naturally validates cycles (by checking if the returned order length matches the number of nodes), `_validate_no_cycles` can simply delegate to it.
**Action:** When validating DAG cycles in the future, avoid redundant graph traversals. Use the result of `topological_sort` to confirm if a cycle exists (O(V+E) instead of 2 * O(V+E)).

## 2024-04-01 - [O(V+E) cascading failures optimization]
**Learning:** Cascading skipped states down a DAG previously required O(V^2) operations because it relied on an iterative loop over all nodes until the graph stabilized. By doing a topological sort first, we can resolve dependencies perfectly in one pass, optimizing this process to O(V+E). We retain the iterative approach in an except block as a fallback for cyclic graphs.
**Action:** When updating states that flow downstream through a graph, always iterate over nodes in topologically sorted order to guarantee O(V+E) time complexity instead of an unpredictable while loop.

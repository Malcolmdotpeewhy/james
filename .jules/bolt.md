## 2024-03-24 - [O(V+E) optimization for DAG sorting]
**Learning:** In the JAMES ExecutionGraph engine (`james/dag.py`), calling `_validate_no_cycles()` followed by `topological_sort()` performs Kahn's algorithm twice over the entire graph. Since `topological_sort` naturally validates cycles (by checking if the returned order length matches the number of nodes), `_validate_no_cycles` can simply delegate to it.
**Action:** When validating DAG cycles in the future, avoid redundant graph traversals. Use the result of `topological_sort` to confirm if a cycle exists (O(V+E) instead of 2 * O(V+E)).

## 2024-04-01 - [O(V+E) cascading failures optimization]
**Learning:** Cascading skipped states down a DAG previously required O(V^2) operations because it relied on an iterative loop over all nodes until the graph stabilized. By doing a topological sort first, we can resolve dependencies perfectly in one pass, optimizing this process to O(V+E). We retain the iterative approach in an except block as a fallback for cyclic graphs.
**Action:** When updating states that flow downstream through a graph, always iterate over nodes in topologically sorted order to guarantee O(V+E) time complexity instead of an unpredictable while loop.

## 2024-04-01 - [Python Generator Overhead in Hot Paths]
**Learning:** Using generator expressions within `all()`, `any()`, and `sum()` in frequently accessed properties (like `is_complete`, `has_failures`, `progress`) and functions (like `get_ready_nodes` in `james/dag.py`) introduces significant function call and frame allocation overhead in Python. When evaluated heavily inside an orchestrator execution loop, these generators become a measurable bottleneck.
**Action:** Replace generator expressions in hot paths with standard `for` loops utilizing early returns (`break` or `return`). This simple optimization yielded a ~1.7x speedup in the DAG ready-node resolution and status-checking loop without sacrificing readability.

## 2024-04-01 - [O(1) Audit Log Count]
**Learning:** Frequent calls to `entry_count` on `james/security.py`'s `AuditLog` caused an O(N) memory and I/O penalty because it read the entire log file, split it into lines, and summed them using a generator expression.
**Action:** Implemented caching for `entry_count`. Upon first access, it reads the file iteratively avoiding `read_text().splitlines()`. Successive records increment this cached count, making `entry_count` an O(1) operation. We also optimized `read_recent` by utilizing `collections.deque` and tail-reading the log instead of loading the entire string.

## 2024-04-01 - [O(1) Data Structures in Polling Loops]
**Learning:** In tight polling loops like `FileWatcher._scan_directory` (`james/watcher.py`) that call `os.walk`, redefining static sets inside the loop (e.g., `{".git", "__pycache__", ...}`) forces unnecessary reallocations on every iteration. Additionally, using `any()` with generator expressions for filtering files adds measurable frame allocation and function call overhead.
**Action:** When writing or optimizing frequently polling loops or hot paths, hoist static data structures to class-level constants. Replace inline generators passed to `any()`, `all()`, or `sum()` with standard `for` loops utilizing early `break` or `return` to avoid per-iteration overhead.

## 2024-04-01 - [Composite Index for Time-Series Queries]
**Learning:** SQLite cannot use two separate single-column indexes (`node_id` and `timestamp`) efficiently for a query that filters on one column and sorts on the other (`WHERE node_id = ? ORDER BY timestamp DESC`). It must choose one index and perform an expensive in-memory sort or full table scan.
**Action:** Always create a composite index `(node_id, timestamp DESC)` for time-series metrics tables to eliminate in-memory sorting, achieving dramatic speedups (e.g., ~200x) for the most common access patterns.

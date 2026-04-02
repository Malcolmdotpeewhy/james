1. **Focus**: Improve error handling and recovery in the Orchestrator's DAG execution engine. Currently, thread crashes are caught, but they don't explicitly transition the node to `FAILED` or cascade the failure, potentially causing the execution loop to deadlock.
2. **Action**:
    - Modify `execute` in `james/orchestrator.py` via `run_in_bash_session` to map futures back to their nodes.
    - Add an exception block when checking thread results to ensure crashed nodes are set to `NodeState.FAILED` with a proper `NodeResult`.
3. **Action**:
    - Add a new test in `james/tests/test_dag_deadlock.py` via `run_in_bash_session` to verify that thread crashes don't cause deadlocks and correctly set node state to `FAILED`.
    - Run the entire test suite via `/home/jules/.local/bin/pytest james/tests/` to verify changes.
4. **Pre-commit**: Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.
5. **Submit**: Create PR for the fix.

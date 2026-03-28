# JAMES (Justified Autonomous Machine for Execution & Systems)

A frontier-class, deterministic autonomous agent designed to solve complex multi-step workflows with zero human intervention. Version 2.3.0.

## Features

- **5-Layer Authority Stack**: Executes across Native, Environmental, Virtual, Synthetic, and Cognitive layers dynamically.
- **DAG Execution Engine**: Transforms flat tasks into parallelized Directed Acyclic Graphs with topological sorting and critical-path optimization.
- **Memory Subsystems**:
  - `STM`: Short-term execution scratchpad.
  - `LTM`: Long-term optimized JSON document store.
  - `RAG`: Local vector database (FAISS) powered by `sentence-transformers` for automated document context ingestion.
- **Self-Evolving Expansion Loop**: If JAMES lacks a tool, it uses the local `llama-server` to automatically synthesize the missing Python code, compiles it in a sandbox, registers it natively to the `ToolRegistry`, and retries the task.
- **Multi-Agent Orchestration**: Auto-routes workloads to specialized sub-agents (`Code`, `Research`, `System`) seamlessly.
- **Observability**: Real-time System Metrics Health Dashboard and SSE Execution Streaming.

## Setup

1. Configure Python 3.10+.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Initialize the environment:
   ```bash
   cp .env.example .env
   # Add your specific configurations
   ```
4. Run the master orchestrator via CLI or Web:
   ```bash
   python -m james.web
   ```

## Development
- Fully offline capable using local `llama-server.exe` (OpenAI-compatible endpoints).
- Dynamically hot-loads external tools from `james/plugins/*/manifest.json`.

*Project developed autonomously via friction-free generation.*

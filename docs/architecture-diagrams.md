# Architecture diagrams

Status: proposed architecture. These diagrams describe intended relationships and enforcement boundaries; they do not represent implemented components.

See the [overall compiler and deployment architecture](architecture.md) for the main system diagram.

## Agent context and verification

The compiler produces context from explicit inputs. Cache reuse is keyed to those inputs, and an edit still passes through current verification. The model receives actionable diagnostics when a change fails.

~~~mermaid
flowchart TD
    Inputs["Source, dependencies, target, policy"] --> Context["Compiler-generated context"]
    Context --> Cache["Versioned context cache"]
    Cache --> Agent["LLM coding agent"]
    Agent --> Patch["Patch with expected revision"]
    Patch --> Check["Compiler and applicable checks"]
    Inputs --> Check
    Policy["Protected execution policy"] --> Check
    Check -->|"Diagnostics"| Agent
    Check -->|"Checks pass"| Change["Checked change"]
~~~

A context cache is not provider prompt caching. A checked change is not proof that every possible defect or attack has been eliminated. The [agent workflow](agent-workflow.md) defines the proposed metadata and evaluation approach.

## Security and release boundaries

The agent can edit source and request bounded tool operations. Protected verification and signing run outside the writable workspace. A native dependency is trusted in-process or executed within a genuinely restricted boundary.

~~~mermaid
flowchart TD
    External["Untrusted packages, docs, tool output"] --> Agent
    External --> Workspace
    subgraph Editable["Agent workspace"]
        Agent["Coding agent"] --> Tools["Restricted tool execution"]
        Tools --> Workspace["Proposed source and dependency changes"]
    end
    Workspace --> Build
    subgraph Protected["Protected build and release system"]
        Policy["Capability and release policy"] --> Build["Isolated build and verification"]
        Build --> Artifact["Checked artifact and provenance"]
        Artifact --> Sign["Protected release signing"]
        Policy --> Sign
    end
    Sign --> Deployment["Deployment with required platform protections"]
    Platform["OS, driver, firmware, hardware trust"] --> Deployment
~~~

Isolation must include actual permission and resource restrictions. A signature does not prove benign behavior. Platform protections have hardware and operational prerequisites and cannot provide an unconditional guarantee after all trusted components are compromised. See the [security design](security.md).

## CPU and GPU resource lifetime

The resource owner must account for work already submitted to a GPU. Host cancellation can end a task's interest in the result without ending device access to memory.

~~~mermaid
sequenceDiagram
    participant Task as CPU task
    participant Runtime as GPU runtime
    participant Memory as Buffer owner
    participant Queue as GPU queue
    Task->>Runtime: Allocate device buffer
    Runtime->>Memory: Create owned allocation
    Memory-->>Task: Buffer handle
    Task->>Runtime: Submit work with buffer
    Runtime->>Memory: Hold allocation for submitted work
    Runtime->>Queue: Submit operation
    alt Task requests cancellation
        Task->>Runtime: Cancel result interest
        Runtime->>Memory: Keep allocation while work is in flight
    else Task awaits result
        Task->>Runtime: Await completion
    end
    Queue-->>Runtime: Operation completed
    Runtime->>Memory: Release submission ownership
    opt No remaining owners or uses
        Memory->>Memory: Reclaim allocation
    end
    opt Task is still awaiting
        Runtime-->>Task: Deliver completion
    end
~~~

This sequence is the normal completion path. Device loss and driver errors require a backend-defined teardown path that establishes when resources are safe to release. Releasing submission ownership does not free a buffer still owned by the application.

The model applies whether ownership is implemented using scoped borrows, explicit retained ownership, or another sound mechanism. It does not require a mandatory global garbage collector. See [GPU and platforms](gpu-platforms.md).


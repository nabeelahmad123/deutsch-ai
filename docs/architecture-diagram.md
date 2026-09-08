# Architecture diagrams

Paste either block straight into `README.md` — GitHub renders Mermaid inline.
To export a PNG/SVG, drop the same code into <https://mermaid.live>.

## System

```mermaid
flowchart TB
    NL["Learner (natural language)<br/><i>I have 10 minutes, German for work</i>"]
    BROWSER["Learner (browser)"]

    subgraph app["Application"]
        direction TB
        AGENT["<b>agent/</b> · orchestrator<br/>Anthropic tool-use loop<br/>parses intent — the only NL step"]
        SPA["<b>frontend/</b> · static SPA (no build)"]
        API["<b>api/</b> · FastAPI<br/>CRUD · /study/* · serves the SPA"]

        subgraph mcp["MCP tool surfaces — independent processes"]
            direction LR
            MCP1["<b>learning_server</b><br/>11 tools + vocab:// resources<br/>streamable-http :8100"]
            MCP2["<b>secondary_server</b><br/>notes vault · 5 tools · :8101"]
        end

        STUDY["<b>study/</b> · quiz + grading<br/>(shared by MCP + API)"]
        CORE["<b>core/</b> · deterministic scheduler<br/>SM-2 · time budget · selection<br/><b>no LLM, no network</b>"]
        TRACER["<b>tracing/</b> · JSONL tracer<br/>name · input · output · latency · ok"]
    end

    DB[("PostgreSQL<br/>words · users · review_logs<br/>card_states · sessions")]
    VAULT[["_vault/*.md"]]
    LLM["Anthropic API<br/>intent loop · semantic grading"]

    subgraph eval["learner_model/ — offline (no DB, no LLM in the loop)"]
        direction LR
        SIM["simulator<br/>forgetting curves"]
        HLR["hlr<br/>Half-Life Regression"]
        EVAL["evaluate<br/>random vs SM-2 vs HLR"]
    end

    NL --> AGENT
    BROWSER --> SPA --> API
    AGENT -->|MCP tools| MCP1
    AGENT -->|MCP tools| MCP2
    AGENT -.-> LLM
    MCP1 --> CORE
    MCP1 --> STUDY
    MCP2 --> VAULT
    API --> CORE
    API --> STUDY
    STUDY -.-> LLM
    CORE --> DB
    API --> DB
    AGENT -.->|every turn / call| TRACER
    MCP1 -.-> TRACER
    MCP2 -.-> TRACER
    EVAL --> SIM
    EVAL --> HLR
```

## CI/CD & deployment

```mermaid
flowchart LR
    DEV["git push → main"]

    subgraph gha["GitHub Actions"]
        direction TB
        CI["<b>ci.yml</b><br/>core + full suites<br/>ruff · black · pytest"]
        BUILD["<b>build-push</b><br/>docker build backend/Dockerfile"]
        DEPLOY["<b>deploy</b><br/>scp compose + Caddyfile<br/>ssh: compose pull &amp;&amp; up -d --wait"]
    end

    GHCR[["GHCR<br/>ghcr.io/nabeelahmad123/deutsch-ai<br/>:latest · :&lt;sha&gt;"]]

    subgraph droplet["DigitalOcean droplet · /opt/learn-german"]
        direction TB
        CADDY["<b>Caddy</b> · auto-TLS · :80/:443"]
        BE["backend · API + SPA · :8000"]
        L1["learning-mcp · :8100"]
        L2["secondary-mcp · :8101"]
        PG[("postgres")]
    end

    USER["https://&lt;name&gt;.duckdns.org"]

    DEV --> CI --> BUILD --> GHCR
    BUILD --> DEPLOY
    DEPLOY -->|over SSH| droplet
    GHCR -.->|docker pull| BE
    USER --> CADDY --> BE
    BE --> PG
    BE -.-> L1
    BE -.-> L2
    L1 --> PG
```

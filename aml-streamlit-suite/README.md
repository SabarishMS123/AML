# AML Compliance Suite

A practical AI-powered Anti-Money Laundering (AML) compliance application that combines:

- deterministic AML rule detection
- Retrieval-Augmented Generation (RAG) over policy documents
- a Groq-powered reasoning layer
- an MCP server exposing AML tools to external clients
- a Streamlit dashboard for demo and evaluation

This project is designed to show how AI can support compliance workflows in a real-world domain by combining rule-based risk detection with policy-grounded LLM reasoning.

---

## Overview

The application allows users to:

- upload AML policy PDFs
- ingest transaction data from CSV files
- detect suspicious customer activity using rule-based checks
- retrieve relevant policy excerpts using vector search
- ask natural-language questions about AML policy content
- evaluate customer risk using a hybrid rule + AI workflow
- expose the same data and actions through an MCP-compatible server

This is a working example of an AI-assisted decision system for AML risk review.

---

## Core Features

### 1. Policy ingestion and semantic search
- Upload AML policy PDFs
- extract text and split into chunks
- generate embeddings with Sentence-Transformers
- store them in Supabase with pgvector support
- retrieve relevant policy clauses using similarity search

### 2. AML risk evaluation engine
The platform evaluates customer activity against classic AML red flags:

- large transaction detection
- velocity / burst pattern detection
- high-risk jurisdiction exposure
- structuring patterns

These checks are implemented in the rule engine and produce structured flags for each customer.

### 3. AI agent-like risk reasoning
For flagged customers, the application:

- collects detected risk factors
- retrieves relevant policy excerpts
- sends the context to Groq LLM
- returns a final risk decision: HIGH, MEDIUM, or LOW
- stores the reasoning and audit trail in the database

This creates an agent-like hybrid workflow: deterministic detection first, then AI reasoning for final decision support.

### 4. RAG-powered policy chatbot
Users can ask policy-related questions in natural language, and the chatbot:

- embeds the query
- finds the most relevant policy chunks
- uses those excerpts as context for the LLM response
- answers while staying grounded in policy text

### 5. MCP server integration
The project exposes AML operations through a FastMCP server, including:

- customer transaction lookup
- policy document search
- manual risk score update

This demonstrates how AI and data tools can be exposed through a standard protocol for interoperability.

---

## Architecture

The application follows a practical hybrid AI architecture:

1. Data ingestion layer
   - uploads PDF policy documents
   - ingests CSV transaction records
   - stores everything in Supabase

2. Retrieval layer
   - chunking + embedding of policy knowledge
   - vector similarity search for policy grounding

3. Decision layer
   - deterministic AML rule engine
   - Groq-based reasoning layer

4. Interface layer
   - Streamlit dashboard
   - MCP server for tool-based access

---

## Tech Stack

- Python 3.11+
- Streamlit
- Sentance-Transformers
- Groq API
- Supabase + PostgreSQL + pgvector
- FastMCP
- Pandas
- PyPDF
- Python-dotenv

---

## Project Structure

```text
aml-streamlit-suite/
├── app.py                          # Main Streamlit app entrypoint
├── requirements.txt               # Project dependencies
├── README.md                      # Project documentation
├── .env.example                   # Sample environment variables
├── database/
│   ├── __init__.py
│   ├── schema.sql                 # Supabase schema and pgvector setup
│   └── supabase_client.py         # Database connection logic
├── services/
│   ├── __init__.py
│   ├── embeddings.py              # Shared embedding utilities
│   ├── aml_agent.py               # AML rule engine + Groq reasoning workflow
│   ├── csv_parser.py              # CSV ingestion and transaction processing
│   ├── pdf_rag.py                 # PDF extraction, chunking, embedding ingestion
│   └── rag_chat.py                # RAG chatbot implementation
├── mcp_server/
│   ├── __init__.py
│   └── server.py                  # MCP server exposing AML tools
└── sample_data/
    └── sample_transactions.csv   # Example transaction dataset
```

---

## Setup Instructions

### 1. Clone or open the project

```bash
cd aml-streamlit-suite
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

- Windows PowerShell
```powershell
.venv\Scripts\Activate.ps1
```

- macOS/Linux
```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root based on `.env.example`:

```env
GROQ_API_KEY=your_groq_api_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_key
```

Important:
- use the Supabase service role key for server-side writes
- do not use the anonymous key for ingestion and updates

### 5. Configure the database

Open your Supabase project and run the SQL from `database/schema.sql`
(fresh install) — this creates every table including `agent_investigations`
(the AI agent's audit trail) and enables the vector retrieval function used
by the app.

**Already have data and don't want to drop tables?** Run the two additive
migrations instead:
```sql
-- database/migration_add_page_number.sql      (adds page-cited RAG chunks)
-- database/migration_add_agent_audit.sql      (adds the agent audit table)
```

---

## Run the Application

### Start the Streamlit app

```bash
streamlit run app.py
```

Then open the local URL shown in the terminal, usually:

```text
http://localhost:8501
```

The new **🤖 AI Investigation Agent** tab needs the same `GROQ_API_KEY` /
`SUPABASE_URL` / `SUPABASE_KEY` already configured above — no extra setup.

### Run the MCP server separately

```bash
python mcp_server/server.py
```

This exposes the AML toolset over MCP for any compatible client or workflow.
The Streamlit-embedded AI agent (see below) calls the *same* tool functions
in-process rather than over the wire — see `mcp_client/agent_mcp_client.py`
for why, and how to swap in a real MCP client session later if needed.

### Run the agent's test scenarios

```bash
python -m unittest agents/test_agent_scenarios.py -v
```

These mock the Groq client and the tool dispatcher, so they run with no API
key and no database connection — they verify the agent's *control flow*
(tool selection, the human-approval gate, JSON parsing, graceful fallback
on a malformed model response), covering the three required scenarios:
a normal customer, a suspicious customer, and insufficient information.

---

## 🤖 AI Investigation Agent

A genuine tool-calling agent layered on top of the existing RAG + MCP
architecture (see `agents/` and `mcp_client/`), distinct from the
deterministic rule-engine + single LLM call in the Risk Dashboard tab.

**Architecture:**
```
Streamlit UI (🤖 AI Investigation Agent tab)
        │
        ▼
agents/aml_investigation_agent.py   — the agentic loop
        │  (Groq function-calling: llama-3.3-70b-versatile)
        ▼
mcp_client/agent_mcp_client.py      — call_tool(name, **kwargs) dispatcher
        │
        ▼
mcp_server/server.py's tool functions   — get_customer_transactions,
        │                                  search_policy_docs,
        │                                  update_customer_risk_score
        ▼
Supabase (customers/transactions) · services/rag_chat.py (existing RAG)
```

**Why this is a real agent, not another fixed pipeline:** the LLM is given
the three tool schemas and decides for itself, turn by turn, whether it
needs transaction data, a policy lookup, neither, or both, and in what
order — the loop in `run_investigation()` just executes whatever the model
asks for and feeds the result back, up to `MAX_TOOL_ITERATIONS` rounds.
Nothing in the Python code hardcodes "always fetch transactions then
always search policy then call the LLM once" the way `services/aml_agent.py`
does for the Risk Dashboard's automated evaluation.

**Human approval gate:** the agent may call `update_customer_risk_score`,
but that specific tool is intercepted before execution — see
`AUTO_EXECUTE_TOOLS` in `mcp_client/agent_mcp_client.py`. The proposed
change is shown in the UI with an **✅ Approve Risk Update** button; only
clicking it actually runs the tool and writes to the database.

**Auditability:** every investigation (approved, rejected, or just
informational) is logged to the `agent_investigations` table via
`services/agent_audit.py` — request, full tool-call trace, parsed
conclusion, and approval status. See the "Recent Investigations" expander
at the bottom of the tab.

**Example inputs to try:**
| Customer ID | Request | Expected outcome |
|---|---|---|
| An existing normal customer | "Investigate this customer and determine the AML risk." | LOW risk, no policy lookup needed, no risk-update recommendation |
| A customer with several transactions just under $10,000 | "Investigate this customer and determine whether the activity is suspicious." | Transaction tool → policy tool (structuring) → HIGH risk with a gated risk-update recommendation |
| A customer ID that doesn't exist, e.g. `CUST-DOES-NOT-EXIST` | "Investigate this customer." | `insufficient_information: true`, risk level `UNKNOWN`, no hallucinated conclusion |

---

## How to Use the App

### Data Ingestion tab
- upload one or more AML policy PDFs
- upload a transaction CSV
- confirm records are stored and embedded

### Risk Dashboard tab
- run the AML evaluation
- review customer risk scores and flagged indicators
- inspect final risk reasoning generated by the LLM

### Policy Chatbot tab
- ask questions such as:
  - what are the rules for suspicious transactions?
  - how should high-risk countries be handled?
  - what does structuring mean under this policy?
- the answer is grounded in the uploaded policy documents

---

## AML Rule Logic

The rule engine currently checks for:

| Rule | Logic |
|---|---|
| Large transaction | any single transaction above $10,000 |
| Velocity | repeated transactions within a short time window |
| High-risk jurisdiction | sender or receiver country matches a configured risky list |
| Structuring | multiple transactions in the $9,000–$9,999 range |

These rules create structured alerts before the LLM performs the final risk determination.

---

## RAG, MCP, and AI Agent Workflow

### RAG
The project uses retrieval-augmented generation to fetch relevant AML policy excerpts and provide grounded answers. This is implemented in the policy chatbot flow and the risk evaluation flow.

### MCP
The app exposes business tools through FastMCP, allowing external clients to access customer and policy information programmatically.

### AI agent workflow
The AML evaluation process behaves like an agent-like workflow:

1. detect risk signals using rules
2. gather relevant policy context via retrieval
3. ask the LLM to reason over the context
4. produce a final decision with justification
5. save the result for auditing and review

This is a hybrid architecture: symbolic rules + retrieval + LLM reasoning.

---

## Known Notes

This project is designed as a strong AI/ML demo and learning project for AML use cases.

Before production deployment, consider adding:

- authentication and authorization
- rate limiting
- secure secret management
- input validation and sanitization
- audit logging and compliance hardening
- model and retention controls for production use

---

## Troubleshooting

### Environment variables not set
Ensure `.env` exists and contains valid values for:

- `GROQ_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_KEY`

### Database errors
Verify that `database/schema.sql` has been executed in Supabase.

### PDF ingestion fails
Make sure the file is text-based or OCR-processed if it is scanned.

### No policy results found in chatbot
Upload policy documents first and ensure the embeddings/indexes are created.

### Groq API errors
Confirm your API key is valid and the model name is still supported by Groq.

---

## Project Summary

This repository demonstrates a realistic AI application for AML compliance:

- rule-driven detection
- semantic policy retrieval
- LLM-based assessment
- tool exposure through MCP
- end-to-end workflow in a user-friendly dashboard

It is a practical example of applying modern AI techniques to a real business problem.

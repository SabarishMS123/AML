# AML Compliance AI Suite

A practical AI-powered Anti-Money Laundering (AML) platform designed to support compliance teams with intelligent risk detection, policy-grounded investigation, and explainable decision support.

This project combines rule-based AML checks with Retrieval-Augmented Generation (RAG), Large Language Model reasoning, and MCP-based tool execution to demonstrate how AI can be applied in a real-world financial compliance workflow.

---

## Project Overview

The application helps teams:

- ingest AML policy documents and transaction data
- detect suspicious customer activity using deterministic rule logic
- retrieve relevant policy clauses through semantic search
- ask natural-language questions about compliance policies
- evaluate risk using a hybrid rule + AI approach
- investigate flagged customers through an agentic workflow with human approval

This is a working prototype for an AI-assisted AML investigation system that blends structured data analysis with contextual policy reasoning.

---

## Why This Project Matters

Modern compliance teams deal with high transaction volumes, regulatory complexity, and the need for explainable decision-making. Traditional review processes are often slow and manual. This project addresses that challenge by creating an intelligent workflow where:

- transaction rules flag suspicious behavior quickly
- AI retrieves policy context from internal documentation
- an investigation agent reasons through the case step by step
- risk updates can be reviewed before being applied

The result is a more transparent, auditable, and operationally useful AML decision-support platform.

---

## Key Features

### 1. AML Risk Evaluation Engine
- Detects red flags such as unusually large transfers, suspicious velocity, high-risk jurisdiction exposure, and structuring patterns
- Produces structured risk signals for each customer
- Helps prioritize cases for manual review

### 2. Policy Ingestion and Semantic Search
- Uploads AML policy PDFs
- Splits documents into chunks and generates embeddings
- Stores policy knowledge in Supabase with pgvector support
- Retrieves the most relevant policy sections using similarity search

### 3. RAG-Powered Policy Chatbot
- Supports natural-language questions about AML rules and policies
- Returns grounded answers using retrieved policy excerpts
- Reduces dependence on unverified AI responses

### 4. AI Investigation Agent
- Uses tool-calling logic to decide when transaction data or policy context is needed
- Investigates customer activity with contextual reasoning
- Includes a human approval checkpoint before a risk score is updated
- Logs investigation history for auditability

### 5. MCP Integration
- Exposes AML-related operations through an MCP-compatible server
- Demonstrates interoperability between AI workflows and external tools
- Shows how enterprise tools can be surfaced in a standard execution model

---

## System Architecture

The solution follows a hybrid AI architecture:

1. Data Layer
   - policy PDFs are uploaded and processed
   - transaction CSVs are ingested into a relational database
   - structured customer and transaction data is stored in Supabase

2. Retrieval Layer
   - PDF content is chunked and embedded
   - vector similarity search retrieves policy context

3. Decision Layer
   - deterministic AML rules identify suspicious patterns
   - Groq-powered reasoning provides final risk interpretation

4. Interface Layer
   - Streamlit dashboard for compliance users
   - AI investigation panel for deeper case review
   - MCP server for tool-based interaction

---

## Tech Stack

- Python 3.11+
- Streamlit
- Supabase + PostgreSQL + pgvector
- Sentence-Transformers
- Groq API
- FastMCP
- Pandas
- PyPDF
- Python-dotenv
- Plotly

---

## Repository Structure

```text
aml-streamlit-suite/
├── app.py                              # Main Streamlit application
├── requirements.txt                   # Python dependencies
├── README.md                          # Project overview and setup guide
├── .env.example                       # Environment variable template
├── agents/
│   ├── __init__.py
│   ├── agent_models.py                # Agent request/result models
│   ├── agent_prompt.py                # Prompt templates
│   ├── aml_investigation_agent.py     # Tool-calling AML investigation workflow
│   └── test_agent_scenarios.py        # Agent test scenarios
├── database/
│   ├── __init__.py
│   ├── schema.sql                     # Database schema and vector setup
│   ├── migration_add_page_number.sql
│   ├── migration_add_agent_audit.sql
│   └── supabase_client.py             # Supabase connection utilities
├── mcp_client/
│   ├── __init__.py
│   └── agent_mcp_client.py            # Client layer for tool dispatch
├── mcp_server/
│   ├── __init__.py
│   └── server.py                      # MCP server exposing AML tools
├── services/
│   ├── __init__.py
│   ├── agent_audit.py                 # Investigation audit logging
│   ├── aml_agent.py                   # AML rule engine and scoring workflow
│   ├── csv_parser.py                  # CSV ingestion and customer processing
│   ├── embeddings.py                  # Embedding utilities
│   ├── pdf_rag.py                     # PDF ingestion and retrieval pipeline
│   ├── rag_chat.py                    # RAG-powered chatbot logic
│   └── ...
├── utils/
│   ├── __init__.py
│   ├── formatting.py
│   └── ui.py

```

---

## How the Application Works

1. Upload AML policy documents and transaction CSV files.
2. The rule engine checks activity against known suspicious patterns.
3. Relevant policy content is retrieved using vector-based semantic search.
4. The LLM interprets the risk context and provides an explainable decision.
5. The AI investigation agent may ask for additional information and propose a risk update.
6. Human approval is required before the update is written to the system.

This creates a practical decision-support workflow for compliance operations.

---

## Setup Instructions

### 1. Clone the repository

```bash
cd aml-streamlit-suite
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

Activate it:

Windows PowerShell:
```powershell
.venv\Scripts\Activate.ps1
```

macOS/Linux:
```bash
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root with:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
SUPABASE_URL=https://jzttmpyzybtlfsukmxpc.supabase.co
SUPABASE_KEY=your_service_role_key
```

### 5. Set up the database

Run the SQL in `database/schema.sql` in your Supabase project. If needed, apply the migration files to extend the schema.

---

## Run the Application

### Start the dashboard

```bash
streamlit run app.py
```

### Run the MCP server separately

```bash
python mcp_server/server.py
```

### Run AI agent scenario tests

```bash
python -m unittest agents/test_agent_scenarios.py -v
```
---

## Demo Video

Add the project demo video link here:


[**PROJECT DEMO VIDEO**](https://drive.google.com/file/d/1VZ0pe1mV96iMJiCt8Z1nhiaO_8rbO-Ub/view?usp=sharing)

---

## Dashboard view
## INGESTION TAB
![Ingestion Tab](images/Ingestion%20Tab.png)
## RISK ANALYSIS TAB
![Risk Tab](images/Risk%20Tab.png)
## RAG BOT TAB
![Rag Tab](images/Rag%20Tab.png)
## INVESTIGATION AGENT TAB
![Investigation Tab](images/Investigation%20Tab.png)

---

## Project Impact

This project demonstrates the ability to build an end-to-end AI application in a high-impact domain:

- AI for financial compliance
- hybrid decision systems combining rules + LLMs
- contextual policy retrieval using RAG
- autonomous investigation workflows with human oversight
- practical use of MCP and agent-driven tool orchestration

It reflects a strong understanding of applied AI, backend integration, data workflows, and explainable decision systems in enterprise environments.

---

## Learnings

This solution showcases practical skills in:

- Python application development
- AI and LLM integration
- semantic search and vector databases
- API/tool orchestration
- workflow design for enterprise use cases
- prototype development in a regulated domain

---
---
## LIVE HOSTED LINK 

[**AML COMPLIANCE SUITE HOSTED LINK **](https://aml-compliance-suite-finzly-project.up.railway.app/)


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
- `GROQ_MODEL`
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


---
## Contact 
EMAIL : mssabarish16@gmail.com
Location : Salem , TN , India
Linked In :https://www.linkedin.com/in/sabarish-m-s/
DEV COMMUNITY : https://dev.to/saboosakthi

---

# PayLabs Hackathon MVP

Auto-reporting MVP for UMKM merchant analytics using:
- PostgreSQL + Adminer
- FastMCP server (read/write tools)
- LangGraph-based reporting agent

## Project Structure

- `docker-compose.yml`: all services (`db`, `adminer`, `mcp-server`, `agent`)
- `init.sql`: schema + seed data (Jan-Feb 2026)
- `mcp-server/app.py`: MCP tools for metrics/query/update/fail flow
- `agent/main.py`: `/generate-report` orchestration
- `skills/analytic-reporting/SKILL.md`: reporting instructions + evidence SQL config
- `agent/agent-curl-commands.md`: agent API test commands
- `mcp-server/mcp-test-commands.md`: MCP tool test commands

## Quick Start

1. Copy env:
```powershell
Copy-Item .env.example .env
```

2. Update secrets in `.env`:
- `POSTGRES_PASSWORD`
- `DB_READ_PASSWORD`
- `DB_WRITE_PASSWORD`
- `AGENT_LLM`

3. Start stack:
```powershell
docker compose up --build -d
```

4. Check health:
```powershell
curl.exe -s http://localhost:8000/health
```

## Services

- Agent API: `http://localhost:8000`
- MCP server: `http://localhost:5001/mcp`
- Adminer UI: `http://localhost:8080`
- PostgreSQL: `localhost:54321`

## Generate Report

Use PowerShell:
```powershell
$body = @{ report_id='january-full'; merchant_id='01'; start_date='2026-01-01'; end_date='2026-01-31' } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri 'http://localhost:8000/generate-report' -ContentType 'application/json' -Body $body
```

Expected success:
- Agent reads metrics + evidence queries
- Writes `report_generation_staging.status='READY'`
- Returns `tool_calls_count`

## Backend Integration

Backend should call:
- `POST /generate-report`
- Base URL example: `http://localhost:8000`
- Content-Type: `application/json`

Required request body parameters:
- `report_id` (string): unique report job id (example: `january-full`)
- `merchant_id` (string): merchant identifier (MVP default: `01`)
- `start_date` (string, `YYYY-MM-DD`)
- `end_date` (string, `YYYY-MM-DD`)

Example JSON:
```json
{
  "report_id": "january-full",
  "merchant_id": "01",
  "start_date": "2026-01-01",
  "end_date": "2026-01-31"
}
```

Success response example:
```json
{
  "ok": true,
  "report_id": "january-full",
  "result": {
    "updated": true,
    "report_id": "january-full",
    "status": "READY",
    "generation_date": "2026-02-26T16:20:51.213587"
  },
  "tool_calls_count": 7
}
```

Failure behavior:
- If any analysis/write step fails, agent marks staging as `FAILED` via MCP `mark_report_failed`.

## Notes

- `.env` is ignored by git (`.gitignore`).
- `report_id` is text-based (examples: `january1`, `january2`).
- On failure, agent calls `mark_report_failed`.

# MCP Testing Commands

```powershell
# Go to project folder
cd d:\Hackathon

# 1) Start/rebuild all containers
docker compose up -d --build

# 2) Check containers
docker compose ps

# 3) Create test staging rows (text report_id)
@'
INSERT INTO report_generation_staging (report_id, merchant_id, status)
VALUES
('january1', '01', 'PROCESSING'),
('january2', '01', 'PROCESSING')
ON CONFLICT (report_id) DO NOTHING;
'@ | docker exec -i paylabs_postgres psql -U paylabs -d paylabs_db
```

```powershell
# 4) MCP: get_report_context
docker exec paylabs_mcp_server python -c "import app; print(app.get_report_context('january1'))"

# 5) MCP: run_read_query (SELECT only)
docker exec paylabs_mcp_server python -c "import app; print(app.run_read_query('SELECT report_id, merchant_id, status FROM report_generation_staging ORDER BY report_id', 10))"

# 6) MCP: run_read_query invalid SQL (should return VALIDATION_ERROR)
docker exec paylabs_mcp_server python -c "import app; print(app.run_read_query('UPDATE report_generation_staging SET status=''READY'' WHERE report_id=''january1'''))"

# 7) MCP: get_report_metrics
docker exec paylabs_mcp_server python -c "import app; print(app.get_report_metrics('01','2026-01-01','2026-01-31'))"

# 8) MCP: update_report_staging (mark READY + fill columns)
docker exec paylabs_mcp_server python -c "import app; print(app.update_report_staging(report_id='january1',status='READY',total_revenue=1500000.00,transaction_count=45,top_selling_item_name='Biskuit',top_selling_item_qty=60,financial_summary='Revenue stable this month',pattern_analysis='Peak sales at 18:00-19:00',strategic_advice='Increase stock for top items')))"

# 9) MCP: update_report_staging invalid status (should return VALIDATION_ERROR)
docker exec paylabs_mcp_server python -c "import app; print(app.update_report_staging('january1','INVALID_STATUS'))"

# 10) MCP: mark_report_failed
docker exec paylabs_mcp_server python -c "import app; print(app.mark_report_failed('january2','Upstream query timeout'))"

# 11) Verify table values from DB
docker exec -i paylabs_postgres psql -U paylabs -d paylabs_db -c "SELECT report_id, merchant_id, status, total_revenue, transaction_count, top_selling_item_name, top_selling_item_qty FROM report_generation_staging WHERE report_id IN ('january1','january2') ORDER BY report_id;"
```

```powershell
# 9) Optional: test hardcoded checker tool (is_report_finished)
# set checker target to january1
(Get-Content .env) -replace '^ACTIVE_REPORT_ID=.*','ACTIVE_REPORT_ID=january1' | Set-Content .env

# recreate only mcp-server to reload env
docker compose up -d --force-recreate mcp-server

# call checker
docker exec paylabs_mcp_server python -c "import app; print(app.is_report_finished())"
```

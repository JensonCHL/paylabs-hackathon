# Agent Curl Commands

## Terminal Example

```cmd
curl -s -X POST http://localhost:8000/generate-report -H "Content-Type: application/json" -d "{\"report_id\":\"january2\",\"merchant_id\":\"01\",\"start_date\":\"2026-01-01\",\"end_date\":\"2026-01-31\"}"
```

```powershell
cd d:\Hackathon
docker compose up -d agent
curl.exe -s http://localhost:8000/health
```

```powershell
$payload = @{ report_id = 'january2'; merchant_id = '01'; start_date = '2026-01-01'; end_date = '2026-01-31' } | ConvertTo-Json -Compress
Invoke-RestMethod -Uri 'http://localhost:8000/generate-report' -Method Post -ContentType 'application/json' -Body $payload | ConvertTo-Json -Compress
```

```bash
curl -s -X POST http://localhost:8000/generate-report \
  -H "Content-Type: application/json" \
  -d '{"report_id":"january2","merchant_id":"01","start_date":"2026-01-01","end_date":"2026-01-31"}'
```

## 1) Health Check

```powershell
curl.exe -s http://localhost:8000/health
```

## 2) Trigger Generate Report

```powershell
$payload = @{ 
  report_id = 'january2'
  merchant_id = '01'
  start_date = '2026-01-01'
  end_date = '2026-01-31'
} | ConvertTo-Json -Compress

Invoke-RestMethod -Uri 'http://localhost:8000/generate-report' -Method Post -ContentType 'application/json' -Body $payload | ConvertTo-Json -Compress
```

## 3) Optional: Verify DB Result

```powershell
docker exec -i paylabs_postgres psql -U paylabs -d paylabs_db -c "SELECT report_id, status, total_revenue, transaction_count, top_selling_item_name, top_selling_item_qty, generation_date FROM report_generation_staging WHERE report_id='january2';"
```

## 4) Optional: cURL-style JSON POST

```powershell
curl.exe -s -X POST http://localhost:8000/generate-report `
  -H "Content-Type: application/json" `
  -d "{\"report_id\":\"january2\",\"merchant_id\":\"01\",\"start_date\":\"2026-01-01\",\"end_date\":\"2026-01-31\"}"
```

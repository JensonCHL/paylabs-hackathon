---
name: analytic-reporting
description: Generate monthly UMKM financial reports from MCP tools and write results to report_generation_staging. Use when backend triggers report generation with report_id, merchant_id, start_date, and end_date, and the agent must produce READY or FAILED status.
---

# Analytic Reporting Skill

## Input Contract

Expect input payload:
- `report_id` (text)
- `merchant_id` (text)
- `start_date` (YYYY-MM-DD)
- `end_date` (YYYY-MM-DD)

Reject request if any field is missing or date range is invalid (`end_date < start_date`).

## Tooling Rules

Use MCP tools:
- `get_report_context(report_id)`
- `get_report_metrics(merchant_id, start_date, end_date)`
- `run_read_query(sql, limit)`
- `update_report_staging(...)`
- `mark_report_failed(report_id, reason)`

Respect MCP response contract:
- Success: `ok=true`, read from `data`
- Error: `ok=false`, read `error.code`, `error.message`, `error.details`

If any required MCP call returns `ok=false`, call `mark_report_failed` and stop.

Mandatory analysis rule:
- Do not rely only on `get_report_metrics`.
- Always call `run_read_query` for additional evidence before finalizing text.
- Use at least 2 focused analytical queries (for example: daily trend, hourly pattern, payment mix concentration, category/item behavior).

## Query Scope Rules

For free query via `run_read_query`:
- Use only `SELECT`
- Keep query limited to requested merchant and date range
- Always include filters on `merchant_id` and `created_at::date BETWEEN start_date AND end_date`
- Use `limit <= 200` unless explicitly needed
- Never query outside reporting purpose

## Runtime Config

Use this machine-readable config for agent query execution:

```json
{
  "evidence_queries": [
    {
      "name": "daily_trend",
      "limit": 200,
      "sql": "SELECT created_at::date AS day, ROUND(SUM(net_amount), 2) AS revenue, COUNT(*) AS tx_count FROM transactions WHERE merchant_id = '{merchant_id}' AND status = 'SUCCESS' AND created_at::date BETWEEN '{start_date}' AND '{end_date}' GROUP BY day ORDER BY day"
    },
    {
      "name": "hourly_pattern",
      "limit": 200,
      "sql": "SELECT EXTRACT(HOUR FROM created_at)::int AS hour_of_day, COUNT(*) AS tx_count, ROUND(SUM(net_amount), 2) AS revenue FROM transactions WHERE merchant_id = '{merchant_id}' AND status = 'SUCCESS' AND created_at::date BETWEEN '{start_date}' AND '{end_date}' GROUP BY hour_of_day ORDER BY tx_count DESC, hour_of_day ASC"
    },
    {
      "name": "payment_mix",
      "limit": 200,
      "sql": "SELECT payment_method, COUNT(*) AS tx_count, ROUND(SUM(net_amount), 2) AS revenue FROM transactions WHERE merchant_id = '{merchant_id}' AND status = 'SUCCESS' AND created_at::date BETWEEN '{start_date}' AND '{end_date}' GROUP BY payment_method ORDER BY tx_count DESC"
    },
    {
      "name": "category_performance",
      "limit": 200,
      "sql": "SELECT ti.category, SUM(ti.quantity) AS total_qty, ROUND(SUM(ti.quantity * ti.unit_price), 2) AS estimated_revenue FROM transaction_items ti JOIN transactions t ON t.transaction_id = ti.transaction_id WHERE t.merchant_id = '{merchant_id}' AND t.status = 'SUCCESS' AND t.created_at::date BETWEEN '{start_date}' AND '{end_date}' GROUP BY ti.category ORDER BY total_qty DESC"
    }
  ],
  "fallback_templates": {
    "financial_summary": "During this reporting window, the business generated total net revenue of IDR {total_revenue} from {transaction_count} successful transactions. The top-selling item was {top_selling_item_name} with total quantity {top_selling_item_qty}, indicating clear product concentration in customer demand. This output is generated in fallback mode because model narrative output was unavailable or did not meet the expected structure. Even in fallback mode, the financial totals and counts are sourced directly from validated MCP tool results and remain reliable for reporting. Use this summary as an operational baseline to compare against previous and upcoming reporting cycles with the same date scope. For richer board-level narrative language, rerun once model output is healthy while preserving the same query scope and report identifier.",
    "pattern_analysis": "The pattern layer used {evidence_count} structured evidence query sets to map transaction behavior across time, payment channels, and product categories. Peak-hour and daily-trend analysis should be interpreted together so short spikes are not mistaken for consistent demand. Payment-method concentration can indicate customer preference strength but should also be reviewed with reliability and failure-rate metrics in production systems. Category and item concentration provide a useful signal for inventory prioritization, especially when one category dominates unit movement. Because this is fallback narrative mode, details remain concise but still grounded in the executed SQL evidence and metric outputs. Treat this as a stable analytical baseline and expand interpretation in advisor mode when qualitative context is required.",
    "strategic_advice": "Prioritize inventory depth and replenishment cadence for high-demand items, especially the current top item {top_selling_item_name}, to reduce lost sales from stock-outs. Align staffing, fulfillment readiness, and campaign timing to observed high-traffic periods instead of spreading effort evenly across low-yield hours. Strengthen dominant payment-channel reliability while creating lightweight incentives for secondary channels to reduce concentration risk and improve conversion resilience. Run short, measurable experiments in weaker periods, then evaluate uplift using the same merchant/date filters to keep results comparable. Review category-level movement weekly and rebalance merchandising focus toward categories with sustained quantity momentum, not one-off spikes. Convert these actions into a recurring monthly operating checklist so the report becomes a decision tool, not just a static summary."
  }
}
```

## Database Structure

Use these tables for reporting queries:

- `merchants`
  - `merchant_id` (text, PK)
  - `business_name` (varchar)
  - `industry_type` (varchar)
  - `join_date` (timestamp)
  - `operating_city` (varchar)

- `transactions`
  - `transaction_id` (uuid, PK)
  - `merchant_id` (text, FK -> merchants.merchant_id)
  - `gross_amount` (numeric)
  - `net_amount` (numeric)
  - `fee_deducted` (numeric)
  - `status` (varchar: SUCCESS, PENDING, FAILED, REFUNDED)
  - `payment_method` (varchar)
  - `created_at` (timestamp)

- `transaction_items`
  - `item_id` (uuid, PK)
  - `transaction_id` (uuid, FK -> transactions.transaction_id)
  - `item_name` (varchar)
  - `category` (varchar)
  - `quantity` (integer)
  - `unit_price` (numeric)

- `report_generation_staging`
  - `report_id` (text, PK)
  - `merchant_id` (text)
  - `generation_date` (timestamp)
  - `status` (varchar: PROCESSING, READY, FAILED)
  - `total_revenue` (numeric)
  - `transaction_count` (integer)
  - `top_selling_item_name` (varchar)
  - `top_selling_item_qty` (integer)
  - `financial_summary` (text)
  - `pattern_analysis` (text)
  - `strategic_advice` (text)

Main join path:
- `transactions.transaction_id = transaction_items.transaction_id`

Main filter pattern:
- `transactions.merchant_id = :merchant_id`
- `transactions.status = 'SUCCESS'`
- `transactions.created_at::date BETWEEN :start_date AND :end_date`

Preferred analysis query patterns:
- Daily revenue trend grouped by date.
- Hourly transaction distribution grouped by hour.
- Payment method distribution grouped by payment method.
- Item/category performance grouped by item/category with `SUM(quantity)` and revenue estimates.

## Reasoning Flow

1. Validate input payload.
2. Read `get_report_context(report_id)` to ensure row exists.
3. Fetch base metrics using `get_report_metrics(...)`.
4. Use `run_read_query` to produce deeper analysis evidence (mandatory).
5. Synthesize metrics + query evidence into narrative insights.
6. Write long-form business narrative fields:
   - `financial_summary`: one detailed paragraph (minimum 6-8 sentences) with numbers, comparisons, and business meaning.
   - `pattern_analysis`: one detailed paragraph (minimum 6-8 sentences) explaining time, payment, and product patterns.
   - `strategic_advice`: one detailed paragraph (minimum 6-8 sentences) with actionable recommendations tied to observed data.
7. Avoid generic statements; each paragraph must reference concrete evidence from tool outputs.
8. Call `update_report_staging` with:
   - `status='READY'`
   - `total_revenue`
   - `transaction_count`
   - `top_selling_item_name`
   - `top_selling_item_qty`
   - drafted text fields
9. Stop execution after successful `READY` update.

## Failure Handling

On failure at any step:
1. Create clear reason text with source error code/message.
2. Call `mark_report_failed(report_id, reason)`.
3. Stop execution.

## Output Policy

Keep text concise, business-readable, and non-technical.
Do not invent values not supported by tool outputs.

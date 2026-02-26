import os
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from mcp.server.fastmcp import FastMCP


mcp = FastMCP(
    "reporting-mcp",
    host=os.getenv("FASTMCP_HOST", "0.0.0.0"),
    port=int(os.getenv("FASTMCP_PORT", "5001")),
)


def _get_db_dsn(user_env: str, password_env: str) -> str:
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    name = os.getenv("DB_NAME")
    user = os.getenv(user_env)
    password = os.getenv(password_env)
    return f"host={host} port={port} dbname={name} user={user} password={password}"


@contextmanager
def _db_read_conn():
    conn = psycopg.connect(_get_db_dsn("DB_READ_USER", "DB_READ_PASSWORD"))
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _db_write_conn():
    conn = psycopg.connect(_get_db_dsn("DB_WRITE_USER", "DB_WRITE_PASSWORD"))
    try:
        yield conn
    finally:
        conn.close()


def _to_float(value: Decimal | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _safe_pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round(((current - previous) / previous) * 100.0, 2)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": data, "error": None}


def _err(error_code: str, error_message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "data": None,
        "error": {
            "code": error_code,
            "message": error_message,
            "details": details or {},
        },
    }


def _handle_error(exc: Exception, details: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(exc, ValueError):
        return _err("VALIDATION_ERROR", str(exc), details)
    if isinstance(exc, psycopg.Error):
        return _err("DATABASE_ERROR", str(exc).strip(), details)
    return _err("INTERNAL_ERROR", str(exc), details)


def _validate_read_query(sql: str) -> str:
    query = sql.strip().rstrip(";")
    lower_query = query.lower()
    if not query:
        raise ValueError("query cannot be empty")
    if ";" in query:
        raise ValueError("only one SQL statement is allowed")
    if not lower_query.startswith("select"):
        raise ValueError("only SELECT queries are allowed")
    blocked = r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do)\b"
    if re.search(blocked, lower_query):
        raise ValueError("query contains blocked SQL keywords")
    return query


@mcp.tool()
def run_read_query(sql: str, limit: int = 200) -> dict[str, Any]:
    try:
        query = _validate_read_query(sql)
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")

        wrapped_query = f"SELECT * FROM ({query}) AS q LIMIT %s"
        with _db_read_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(wrapped_query, (limit,))
                rows = cur.fetchall()
                columns = [desc.name for desc in cur.description or []]

        data_rows = []
        for row in rows:
            data_rows.append({k: _json_safe(v) for k, v in zip(columns, row)})

        return _ok(
            {
                "row_count": len(data_rows),
                "limit": limit,
                "columns": columns,
                "rows": data_rows,
            }
        )
    except Exception as exc:
        return _handle_error(exc, {"tool": "run_read_query"})


@mcp.tool()
def get_report_context(report_id: str) -> dict[str, Any]:
    try:
        with _db_read_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT report_id, merchant_id, generation_date, status
                    FROM report_generation_staging
                    WHERE report_id = %s
                    """,
                    (report_id,),
                )
                row = cur.fetchone()

        if not row:
            return _ok({"found": False, "report_id": report_id})

        return _ok(
            {
                "found": True,
                "report_id": str(row[0]),
                "merchant_id": row[1],
                "generation_date": row[2].isoformat() if row[2] else None,
                "status": row[3],
            }
        )
    except Exception as exc:
        return _handle_error(exc, {"tool": "get_report_context", "report_id": report_id})


@mcp.tool()
def get_report_metrics(merchant_id: str, start_date: str, end_date: str) -> dict[str, Any]:
    try:
        start = _parse_date(start_date)
        end = _parse_date(end_date)
        if end < start:
            raise ValueError("end_date must be >= start_date")

        days = (end - start).days + 1
        prev_start = start - timedelta(days=days)
        prev_end = start - timedelta(days=1)

        with _db_read_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COALESCE(SUM(net_amount), 0) AS total_revenue,
                        COUNT(*) AS transaction_count
                    FROM transactions
                    WHERE merchant_id = %s
                      AND status = 'SUCCESS'
                      AND created_at::date BETWEEN %s AND %s
                    """,
                    (merchant_id, start, end),
                )
                total_revenue, transaction_count = cur.fetchone()

                cur.execute(
                    """
                    SELECT
                        ti.item_name,
                        SUM(ti.quantity) AS total_qty
                    FROM transaction_items ti
                    JOIN transactions t ON t.transaction_id = ti.transaction_id
                    WHERE t.merchant_id = %s
                      AND t.status = 'SUCCESS'
                      AND t.created_at::date BETWEEN %s AND %s
                    GROUP BY ti.item_name
                    ORDER BY total_qty DESC, ti.item_name ASC
                    LIMIT 1
                    """,
                    (merchant_id, start, end),
                )
                top_item = cur.fetchone()

                cur.execute(
                    """
                    SELECT
                        EXTRACT(HOUR FROM created_at)::int AS hour_of_day,
                        COUNT(*) AS tx_count
                    FROM transactions
                    WHERE merchant_id = %s
                      AND status = 'SUCCESS'
                      AND created_at::date BETWEEN %s AND %s
                    GROUP BY hour_of_day
                    ORDER BY tx_count DESC, hour_of_day ASC
                    LIMIT 1
                    """,
                    (merchant_id, start, end),
                )
                peak = cur.fetchone()

                cur.execute(
                    """
                    SELECT payment_method, COUNT(*) AS tx_count
                    FROM transactions
                    WHERE merchant_id = %s
                      AND status = 'SUCCESS'
                      AND created_at::date BETWEEN %s AND %s
                    GROUP BY payment_method
                    ORDER BY tx_count DESC
                    """,
                    (merchant_id, start, end),
                )
                payment_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT COALESCE(SUM(net_amount), 0)
                    FROM transactions
                    WHERE merchant_id = %s
                      AND status = 'SUCCESS'
                      AND created_at::date BETWEEN %s AND %s
                    """,
                    (merchant_id, prev_start, prev_end),
                )
                prev_revenue = cur.fetchone()[0]

        top_selling_item_name = top_item[0] if top_item else None
        top_selling_item_qty = int(top_item[1]) if top_item else 0

        peak_window = None
        if peak:
            hour = int(peak[0])
            peak_window = f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"

        total_revenue_f = _to_float(total_revenue)
        prev_revenue_f = _to_float(prev_revenue)

        return _ok(
            {
                "merchant_id": merchant_id,
                "start_date": start_date,
                "end_date": end_date,
                "total_revenue": round(total_revenue_f, 2),
                "transaction_count": int(transaction_count or 0),
                "top_selling_item_name": top_selling_item_name,
                "top_selling_item_qty": top_selling_item_qty,
                "peak_sales_hour": peak_window,
                "payment_method_breakdown": [
                    {"payment_method": row[0], "transaction_count": int(row[1])}
                    for row in payment_rows
                ],
                "previous_period_start": prev_start.isoformat(),
                "previous_period_end": prev_end.isoformat(),
                "previous_period_revenue": round(prev_revenue_f, 2),
                "revenue_change_pct": _safe_pct_change(total_revenue_f, prev_revenue_f),
            }
        )
    except Exception as exc:
        return _handle_error(
            exc,
            {
                "tool": "get_report_metrics",
                "merchant_id": merchant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )


@mcp.tool()
def update_report_staging(
    report_id: str,
    status: str,
    total_revenue: float | None = None,
    transaction_count: int | None = None,
    top_selling_item_name: str | None = None,
    top_selling_item_qty: int | None = None,
    financial_summary: str | None = None,
    pattern_analysis: str | None = None,
    strategic_advice: str | None = None,
) -> dict[str, Any]:
    try:
        allowed = {"PROCESSING", "READY", "FAILED"}
        status_upper = status.upper()
        if status_upper not in allowed:
            raise ValueError(f"status must be one of {sorted(allowed)}")

        with _db_write_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE report_generation_staging
                    SET
                        status = %s,
                        total_revenue = COALESCE(%s, total_revenue),
                        transaction_count = COALESCE(%s, transaction_count),
                        top_selling_item_name = COALESCE(%s, top_selling_item_name),
                        top_selling_item_qty = COALESCE(%s, top_selling_item_qty),
                        financial_summary = COALESCE(%s, financial_summary),
                        pattern_analysis = COALESCE(%s, pattern_analysis),
                        strategic_advice = COALESCE(%s, strategic_advice),
                        generation_date = CURRENT_TIMESTAMP
                    WHERE report_id = %s
                    RETURNING report_id, status, generation_date
                    """,
                    (
                        status_upper,
                        total_revenue,
                        transaction_count,
                        top_selling_item_name,
                        top_selling_item_qty,
                        financial_summary,
                        pattern_analysis,
                        strategic_advice,
                        report_id,
                    ),
                )
                row = cur.fetchone()
            conn.commit()

        if not row:
            return _ok({"updated": False, "report_id": report_id})

        return _ok(
            {
                "updated": True,
                "report_id": str(row[0]),
                "status": row[1],
                "generation_date": row[2].isoformat() if row[2] else None,
            }
        )
    except Exception as exc:
        return _handle_error(exc, {"tool": "update_report_staging", "report_id": report_id})


@mcp.tool()
def mark_report_failed(report_id: str, reason: str) -> dict[str, Any]:
    try:
        return update_report_staging(
            report_id=report_id,
            status="FAILED",
            financial_summary=f"Report generation failed: {reason}",
        )
    except Exception as exc:
        return _handle_error(exc, {"tool": "mark_report_failed", "report_id": report_id})


@mcp.tool()
def is_report_finished() -> dict[str, Any]:
    try:
        report_id = os.getenv("ACTIVE_REPORT_ID", "")
        if not report_id:
            return _err(
                "CONFIG_ERROR",
                "ACTIVE_REPORT_ID is not set",
                {"tool": "is_report_finished"},
            )

        with _db_read_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, generation_date
                    FROM report_generation_staging
                    WHERE report_id = %s
                    """,
                    (report_id,),
                )
                row = cur.fetchone()

        if not row:
            return _ok(
                {
                    "configured": True,
                    "found": False,
                    "report_id": report_id,
                }
            )

        status = row[0]
        return _ok(
            {
                "configured": True,
                "found": True,
                "report_id": report_id,
                "status": status,
                "finished": status in {"READY", "FAILED"},
                "generation_date": row[1].isoformat() if row[1] else None,
            }
        )
    except Exception as exc:
        return _handle_error(exc, {"tool": "is_report_finished"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

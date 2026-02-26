import os
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, TypedDict

from fastapi import FastAPI, HTTPException
from langchain_core.prompts import ChatPromptTemplate
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, field_validator


logging.basicConfig(
    level=os.getenv("AGENT_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("paylabs-agent")


class ReportRequest(BaseModel):
    report_id: str
    merchant_id: str
    start_date: str
    end_date: str

    @field_validator("report_id", "merchant_id")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value

    @field_validator("end_date")
    @classmethod
    def validate_date_range(cls, end_date: str, info) -> str:
        start_date = info.data.get("start_date")
        if start_date:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
            if end < start:
                raise ValueError("end_date must be >= start_date")
        return end_date


class AgentState(TypedDict, total=False):
    input: dict[str, Any]
    context: dict[str, Any]
    metrics: dict[str, Any]
    evidence: dict[str, Any]
    narratives: dict[str, str]
    update_result: dict[str, Any]
    error: str
    tool_calls_count: int


class AgentRuntime:
    def __init__(self) -> None:
        self.skill_text = self._load_skill()
        self.skill_config = self._extract_skill_config(self.skill_text)
        self.mcp_client: MultiServerMCPClient | None = None
        self.tools: dict[str, Any] = {}
        self.llm: ChatOpenAI | None = None
        self.graph = self._build_graph()

    def _load_skill(self) -> str:
        skill_path = Path(
            os.getenv("SKILL_PATH", "/app/skills/analytic-reporting/SKILL.md")
        )
        if skill_path.exists():
            return skill_path.read_text(encoding="utf-8")
        return "Use MCP tools safely. Output concise business analysis."

    def _extract_skill_config(self, skill_text: str) -> dict[str, Any]:
        json_blocks = re.findall(r"```json\s*(\{[\s\S]*?\})\s*```", skill_text)
        for raw in json_blocks:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and "evidence_queries" in parsed:
                    return parsed
            except json.JSONDecodeError:
                continue
        return {"evidence_queries": []}

    def _render_sql_template(self, sql_template: str, payload: dict[str, Any]) -> str:
        rendered = sql_template
        rendered = rendered.replace("{merchant_id}", str(payload["merchant_id"]))
        rendered = rendered.replace("{start_date}", str(payload["start_date"]))
        rendered = rendered.replace("{end_date}", str(payload["end_date"]))
        return rendered

    def _escape_for_prompt_template(self, text: str) -> str:
        return text.replace("{", "{{").replace("}", "}}")

    def _extract_json_object(self, text: str) -> dict[str, Any] | None:
        content = text.strip()
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
        if fence_match:
            try:
                parsed = json.loads(fence_match.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            maybe_json = content[first_brace : last_brace + 1]
            try:
                parsed = json.loads(maybe_json)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        return None

    async def startup(self) -> None:
        mcp_url = os.getenv("MCP_URL", "http://mcp-server:5001/mcp")
        self.mcp_client = MultiServerMCPClient(
            {"reporting": {"transport": "streamable_http", "url": mcp_url}}
        )
        tool_list = await self.mcp_client.get_tools()
        self.tools = {tool.name: tool for tool in tool_list}

        api_key = os.getenv("AGENT_LLM", os.getenv("OPENAI_API_KEY", "")).strip()
        base_url = os.getenv("AGENT_BASE_URL", os.getenv("OPENAI_BASE_URL", "")).strip()
        model = os.getenv("AGENT_MODEL", os.getenv("OPENAI_MODEL", "qwen-plus"))
        if api_key:
            kwargs: dict[str, Any] = {"model": model, "api_key": api_key, "temperature": 0.1}
            if base_url:
                kwargs["base_url"] = base_url
            self.llm = ChatOpenAI(**kwargs)
        logger.info(
            "Agent startup complete | tools_loaded=%s | llm_enabled=%s | model=%s",
            len(self.tools),
            bool(self.llm),
            model,
        )

    def _redact(self, payload: dict[str, Any]) -> dict[str, Any]:
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if any(secret in key.lower() for secret in ["key", "token", "password", "secret"]):
                redacted[key] = "***"
            else:
                redacted[key] = value
        return redacted

    async def _mcp_call(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        logger.info("MCP call start | tool=%s | payload=%s", tool_name, self._redact(payload))
        tool = self.tools.get(tool_name)
        if not tool:
            result = {"ok": False, "error": {"code": "TOOL_NOT_FOUND", "message": tool_name}}
            logger.error("MCP call failed | tool=%s | result=%s", tool_name, result)
            return result
        result = await tool.ainvoke(payload)
        if isinstance(result, dict):
            logger.info("MCP call end | tool=%s | result=%s", tool_name, result)
            return result
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    logger.info("MCP call end | tool=%s | result=%s", tool_name, parsed)
                    return parsed
            except json.JSONDecodeError:
                pass
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        try:
                            parsed = json.loads(text)
                            if isinstance(parsed, dict):
                                logger.info("MCP call end | tool=%s | result=%s", tool_name, parsed)
                                return parsed
                        except json.JSONDecodeError:
                            continue
        invalid = {"ok": False, "error": {"code": "INVALID_TOOL_RESPONSE", "message": str(result)}}
        logger.error("MCP call failed | tool=%s | result=%s", tool_name, invalid)
        return invalid

    def _fallback_narratives(self, metrics: dict[str, Any], evidence: dict[str, Any]) -> dict[str, str]:
        total_revenue = metrics.get("total_revenue", 0)
        transaction_count = metrics.get("transaction_count", 0)
        fallback_cfg = self.skill_config.get("fallback_templates", {})
        financial_tpl = fallback_cfg.get(
            "financial_summary",
            "Total net revenue is IDR {total_revenue} from {transaction_count} successful transactions.",
        )
        pattern_tpl = fallback_cfg.get(
            "pattern_analysis",
            "Evidence queries executed: {evidence_count}. Use current metrics and evidence for pattern interpretation.",
        )
        advice_tpl = fallback_cfg.get(
            "strategic_advice",
            "Prioritize top-demand items and validate impact weekly using the same query scope.",
        )

        format_data = {
            "total_revenue": f"{total_revenue:,.2f}",
            "transaction_count": transaction_count,
            "evidence_count": len(evidence),
            "top_selling_item_name": metrics.get("top_selling_item_name", "N/A"),
            "top_selling_item_qty": metrics.get("top_selling_item_qty", 0),
            "peak_sales_hour": metrics.get("peak_sales_hour", "N/A"),
            "revenue_change_pct": metrics.get("revenue_change_pct", "N/A"),
            "previous_period_revenue": metrics.get("previous_period_revenue", 0),
        }

        financial_summary = str(financial_tpl).format(**format_data)
        pattern_analysis = str(pattern_tpl).format(**format_data)
        strategic_advice = str(advice_tpl).format(**format_data)

        return {
            "financial_summary": financial_summary,
            "pattern_analysis": pattern_analysis,
            "strategic_advice": strategic_advice,
        }

    def _build_graph(self):
        graph = StateGraph(AgentState)

        async def validate_input(state: AgentState) -> AgentState:
            payload = state["input"]
            if not payload.get("report_id") or not payload.get("merchant_id"):
                state["error"] = "Missing report_id or merchant_id"
            return state

        async def validate_report_context(state: AgentState) -> AgentState:
            if state.get("error"):
                return state
            payload = state["input"]
            state["tool_calls_count"] = state.get("tool_calls_count", 0) + 1
            result = await self._mcp_call(
                "get_report_context",
                {"report_id": payload["report_id"]},
            )
            if not result.get("ok"):
                state["error"] = f"get_report_context failed: {result.get('error', {}).get('message', 'unknown')}"
                return state
            context_data = result.get("data", {})
            if not context_data.get("found"):
                state["error"] = f"report_id not found: {payload['report_id']}"
                return state
            context_merchant_id = context_data.get("merchant_id")
            if context_merchant_id and context_merchant_id != payload["merchant_id"]:
                state["error"] = "merchant_id mismatch between request and staging context"
                return state
            state["context"] = context_data
            return state

        async def fetch_metrics(state: AgentState) -> AgentState:
            if state.get("error"):
                return state
            payload = state["input"]
            state["tool_calls_count"] = state.get("tool_calls_count", 0) + 1
            result = await self._mcp_call(
                "get_report_metrics",
                {
                    "merchant_id": payload["merchant_id"],
                    "start_date": payload["start_date"],
                    "end_date": payload["end_date"],
                },
            )
            if not result.get("ok"):
                state["error"] = f"get_report_metrics failed: {result.get('error', {}).get('message', 'unknown')}"
                return state
            state["metrics"] = result["data"]
            return state

        async def fetch_evidence(state: AgentState) -> AgentState:
            if state.get("error"):
                return state
            payload = state["input"]
            queries = self.skill_config.get("evidence_queries", [])
            if not isinstance(queries, list) or len(queries) < 2:
                state["error"] = "Skill config must provide at least 2 evidence_queries in SKILL.md"
                return state

            evidence: dict[str, Any] = {}
            for query_cfg in queries:
                if not isinstance(query_cfg, dict):
                    state["error"] = "Invalid evidence query config format"
                    return state
                key = str(query_cfg.get("name", "query"))
                sql_template = str(query_cfg.get("sql", "")).strip()
                if not sql_template:
                    state["error"] = f"Missing SQL template for evidence query: {key}"
                    return state
                sql = self._render_sql_template(sql_template, payload)
                limit = int(query_cfg.get("limit", 200))
                state["tool_calls_count"] = state.get("tool_calls_count", 0) + 1
                result = await self._mcp_call(
                    "run_read_query",
                    {"sql": sql, "limit": limit},
                )
                if not result.get("ok"):
                    state["error"] = f"run_read_query failed ({key}): {result.get('error', {}).get('message', 'unknown')}"
                    return state
                evidence[key] = result.get("data", {})

            state["evidence"] = evidence
            return state

        async def draft_narratives(state: AgentState) -> AgentState:
            if state.get("error"):
                return state
            metrics = state.get("metrics", {})
            evidence = state.get("evidence", {})
            if not self.llm:
                state["narratives"] = self._fallback_narratives(metrics, evidence)
                return state

            prompt = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "Follow these instructions strictly:\n"
                        f"{self._escape_for_prompt_template(self.skill_text)}\n"
                        "Return valid JSON with exactly these keys: financial_summary, pattern_analysis, strategic_advice.",
                    ),
                    ("human", "Metrics:\n{metrics}\n\nEvidence from run_read_query:\n{evidence}"),
                ]
            )
            chain = prompt | self.llm
            try:
                response = await chain.ainvoke({"metrics": metrics, "evidence": evidence})
                text = response.content if hasattr(response, "content") else str(response)
                logger.info("LLM narrative raw output | text=%s", str(text))
            except Exception as exc:
                logger.error("LLM narrative generation failed | error=%s", str(exc))
                state["narratives"] = self._fallback_narratives(metrics, evidence)
                return state

            parsed = self._extract_json_object(str(text))

            if not parsed:
                logger.warning("LLM narrative parse failed; using fallback template")
                state["narratives"] = self._fallback_narratives(metrics, evidence)
                return state

            required = ["financial_summary", "pattern_analysis", "strategic_advice"]
            if not all(isinstance(parsed.get(k), str) and parsed.get(k).strip() for k in required):
                logger.warning("LLM narrative missing required fields; using fallback template")
                state["narratives"] = self._fallback_narratives(metrics, evidence)
                return state

            state["narratives"] = {k: parsed[k].strip() for k in required}
            return state

        async def write_ready(state: AgentState) -> AgentState:
            if state.get("error"):
                return state
            payload = state["input"]
            metrics = state["metrics"]
            narratives = state["narratives"]
            state["tool_calls_count"] = state.get("tool_calls_count", 0) + 1
            result = await self._mcp_call(
                "update_report_staging",
                {
                    "report_id": payload["report_id"],
                    "status": "READY",
                    "total_revenue": metrics.get("total_revenue"),
                    "transaction_count": metrics.get("transaction_count"),
                    "top_selling_item_name": metrics.get("top_selling_item_name"),
                    "top_selling_item_qty": metrics.get("top_selling_item_qty"),
                    "financial_summary": narratives.get("financial_summary"),
                    "pattern_analysis": narratives.get("pattern_analysis"),
                    "strategic_advice": narratives.get("strategic_advice"),
                },
            )
            if not result.get("ok"):
                state["error"] = f"update_report_staging failed: {result.get('error', {}).get('message', 'unknown')}"
                return state
            state["update_result"] = result["data"]
            return state

        async def mark_failed(state: AgentState) -> AgentState:
            error_text = state.get("error", "Unknown error")
            payload = state.get("input", {})
            report_id = payload.get("report_id", "")
            if report_id:
                state["tool_calls_count"] = state.get("tool_calls_count", 0) + 1
                await self._mcp_call(
                    "mark_report_failed",
                    {"report_id": report_id, "reason": error_text},
                )
            return state

        def route_after_write(state: AgentState) -> str:
            return "fail" if state.get("error") else "end"

        graph.add_node("validate", validate_input)
        graph.add_node("context", validate_report_context)
        graph.add_node("metrics", fetch_metrics)
        graph.add_node("evidence", fetch_evidence)
        graph.add_node("narratives", draft_narratives)
        graph.add_node("write_ready", write_ready)
        graph.add_node("fail", mark_failed)

        graph.set_entry_point("validate")
        graph.add_edge("validate", "context")
        graph.add_edge("context", "metrics")
        graph.add_edge("metrics", "evidence")
        graph.add_edge("evidence", "narratives")
        graph.add_edge("narratives", "write_ready")
        graph.add_conditional_edges(
            "write_ready",
            route_after_write,
            {"fail": "fail", "end": END},
        )
        graph.add_edge("fail", END)

        return graph.compile()

    async def run(self, request: ReportRequest) -> dict[str, Any]:
        logger.info("Agent run start | request=%s", request.model_dump())
        final_state = await self.graph.ainvoke({"input": request.model_dump(), "tool_calls_count": 0})
        tool_calls = final_state.get("tool_calls_count", 0)
        logger.info("Agent run state | report_id=%s | state=%s", request.report_id, final_state)
        if final_state.get("error"):
            response = {
                "ok": False,
                "error": final_state["error"],
                "report_id": request.report_id,
                "tool_calls_count": tool_calls,
            }
            logger.error("Agent run failed | response=%s", response)
            return response
        response = {
            "ok": True,
            "report_id": request.report_id,
            "result": final_state.get("update_result", {}),
            "tool_calls_count": tool_calls,
        }
        logger.info("Agent run success | tool_calls_count=%s | response=%s", tool_calls, response)
        return response


runtime = AgentRuntime()
app = FastAPI(title="Reporting Agent", version="0.1.0")


@app.on_event("startup")
async def _startup() -> None:
    await runtime.startup()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "tools_loaded": len(runtime.tools)}


@app.post("/generate-report")
async def generate_report(payload: ReportRequest) -> dict[str, Any]:
    logger.info("HTTP /generate-report called | payload=%s", payload.model_dump())
    result = await runtime.run(payload)
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result)
    return result

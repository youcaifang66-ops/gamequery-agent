from dataclasses import asdict

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.metric_info import MetricInfo
from app.prompt.prompt_loader import load_prompt
from app.retrieval.online import retrieve_metadata_candidates


async def _expand_keywords(query: str) -> list[str]:
    prompt = PromptTemplate(
        template=load_prompt("extend_keywords_for_metric_recall"),
        input_variables=["query"],
    )
    return await (prompt | llm | JsonOutputParser()).ainvoke({"query": query})


async def recall_metric(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    step = "召回指标信息"
    writer({"type": "progress", "step": step, "status": "running"})
    try:
        query = state["query"]
        fused = await retrieve_metadata_candidates(
            entity_type="metric",
            query=query,
            exact_terms=state["keywords"],
            expanded_terms=await _expand_keywords(query),
            embedding_client=runtime.context["embedding_client"],
            repository=runtime.context["metric_qdrant_repository"],
        )
        writer({"type": "progress", "step": step, "status": "success"})
        return {
            "retrieved_metric_infos": [
                MetricInfo(**candidate.payload) for candidate in fused
            ],
            "metric_retrieval_evidence": [
                {
                    "entity_type": candidate.entity_type,
                    "entity_id": candidate.candidate_id,
                    "score": candidate.score,
                    "evidence": [asdict(item) for item in candidate.evidence],
                }
                for candidate in fused
            ],
        }
    except Exception as error:
        logger.error(f"{step} failed: {type(error).__name__}")
        writer({"type": "progress", "step": step, "status": "error"})
        raise

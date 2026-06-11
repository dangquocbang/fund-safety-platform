from __future__ import annotations
import asyncio
from pathlib import Path

from .indexer import build_method_index, render_index_text, entries_to_dict
from .discovery import discover_targets, discover_from_entrypoints, discover_targets_with_llm, render_targets_yaml, targets_to_dict
from .assessor import assess_targets, assess_targets_with_llm, target_assessments_to_dict, findings_from_target_assessments, build_audit_summary
from .graph import build_call_graph, infer_key_flow
from .models import Assessment, Severity
from .report import write_reports
from .knowledge import build_knowledge_graph
from .risk_score import compute_service_risk_scores
from .autofix import suggest_patch
from .llm import LLMClient, should_review, review_with_ollama
from app.config import MAX_LLM_TARGETS, DISCOVERY_MAX_TARGETS, ASSESSMENT_BATCH_SIZE, ASSESSMENT_MAX_TARGETS, DISCOVERY_CONFIG


def run_fund_safety_scan(
    source: str | Path,
    out: str | Path,
    project: str = "local-project",
    llm: bool = False,
    depth: int = 2,
    llm_provider: str | None = None,
    artifact_prefix: str | None = None,
) -> Assessment:
    """Index-first fund-safety audit pipeline.

    This mirrors the original high-accuracy workflow:
      1. build_index: create compact method/API index from Java/Go source
      2. discovery depth=2: select target methods and reachable evidence
      3. assessment: evaluate R1-R10 only for discovered targets
      4. graph/risk/chat artifacts: store structured evidence for UI

    The key design choice is conservative targeting: the scanner does not audit
    every method with a fund keyword. It audits only discovered business methods
    and their depth=2 reachable evidence.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    methods, index_entries = build_method_index(source)
    edges = build_call_graph(methods)
    key_flows = infer_key_flow(methods)

    # Multi-provider pipeline. Discovery and assessment can use different engines.
    # Example: discovery=claude_code/ollama, assessment=junie/claude_code/openai/ollama.
    discovery_client = LLMClient.for_stage("discovery")
    assessment_client = LLMClient.for_stage("assessment")
    if llm_provider:
        # Backward-compatible override: apply the same provider to both stages only when explicitly passed.
        discovery_client.config.provider = llm_provider
        assessment_client.config.provider = llm_provider

    use_discovery_llm = bool(llm and discovery_client.enabled)
    use_assessment_llm = bool(llm and assessment_client.enabled)

    entrypoint_mode = bool(DISCOVERY_CONFIG.get("entrypoint_mode", True))

    if use_discovery_llm:
        discovery_targets = discover_targets_with_llm(
            index_entries,
            methods,
            edges,
            project=project,
            depth=depth,
            llm_client=discovery_client,
            source_root=str(source),
            max_targets=DISCOVERY_MAX_TARGETS,
        )
    elif entrypoint_mode:
        discovery_targets = discover_from_entrypoints(
            index_entries, methods, edges, depth=depth, max_targets=DISCOVERY_MAX_TARGETS,
        )
        # Fallback to hint-based discovery if no entrypoints were detected
        # (e.g. codebase uses a framework we don't recognise yet).
        if not discovery_targets:
            discovery_targets = discover_targets(index_entries, methods, edges, depth=depth, max_targets=DISCOVERY_MAX_TARGETS)
    else:
        discovery_targets = discover_targets(index_entries, methods, edges, depth=depth, max_targets=DISCOVERY_MAX_TARGETS)

    discovery_targets = discovery_targets[:ASSESSMENT_MAX_TARGETS]

    if use_assessment_llm:
        target_assessments = assess_targets_with_llm(
            discovery_targets,
            methods,
            edges,
            project=project,
            llm_client=assessment_client,
            source_root=str(source),
            batch_size=ASSESSMENT_BATCH_SIZE,
        )
    else:
        target_assessments = assess_targets(discovery_targets, methods, edges)

    # Findings are now derived from the R1-R10 assessment artifact.
    # This matches the original Claude/Junie workflow and avoids free-form keyword findings.
    findings = findings_from_target_assessments(target_assessments)

    for finding in findings:
        finding.autofix_patch = suggest_patch(finding)

    # Optional secondary high-risk review. Usually disabled because assessment provider already performed R1-R10 reasoning.
    if llm and not use_assessment_llm:
        async def _run_llm_reviews():
            selected = [f for f in findings if should_review(f)][:MAX_LLM_TARGETS]
            reviews = await asyncio.gather(*[review_with_ollama(f) for f in selected])
            for f, review in zip(selected, reviews):
                f.llm_review = review
        asyncio.run(_run_llm_reviews())

    by_severity = {s.value: sum(1 for f in findings if f.severity == s) for s in Severity}
    summary = dict(by_severity)
    audit_summary = build_audit_summary(project, target_assessments)
    summary.update({
        "finding_count": len(findings),
        "by_severity": by_severity,
        "indexed_methods": len(index_entries),
        "discovery_targets": len(discovery_targets),
        "target_assessments": len(target_assessments),
        "audit_pipeline": "upload_zip_to_python_build_index_to_discovery_provider_to_targets_yml_to_assessment_provider_to_r1_r11_matrix",
        "llm_enabled": bool(use_discovery_llm or use_assessment_llm),
        "discovery_provider": discovery_client.config.provider,
        "assessment_provider": assessment_client.config.provider,
        "audit_summary": audit_summary,
        "total_functions_audited": audit_summary["total_functions_audited"],
        "p0_with_fail": audit_summary["p0_with_fail"],
        "p0_with_partial": audit_summary["p0_with_partial"],
    })
    knowledge_nodes, knowledge_edges = build_knowledge_graph(methods, edges, key_flows, findings)
    risk_scores = compute_service_risk_scores(methods, findings)
    summary["risk_scores"] = [r.model_dump() for r in risk_scores]
    summary["knowledge_graph"] = {"nodes": len(knowledge_nodes), "edges": len(knowledge_edges)}

    assessed_method_ids = {ta.method_id for ta in discovery_targets}
    filtered_methods = [m for m in methods if m.id in assessed_method_ids]
    filtered_edges = [e for e in edges if e.source in assessed_method_ids and e.target in assessed_method_ids]

    assessment = Assessment(
        project=project,
        summary=summary,
        index_entries=entries_to_dict(index_entries),
        discovery_targets=targets_to_dict(discovery_targets),
        target_assessments=target_assessments_to_dict(target_assessments),
        methods=filtered_methods,
        call_edges=filtered_edges,
        key_flows=key_flows,
        findings=findings,
        knowledge_nodes=knowledge_nodes,
        knowledge_edges=knowledge_edges,
        risk_scores=risk_scores,
    )

    (out / "index.txt").write_text(render_index_text(index_entries, project), encoding="utf-8")
    (out / "targets.yml").write_text(render_targets_yaml(project, discovery_targets), encoding="utf-8")
    write_reports(assessment, out, artifact_prefix=artifact_prefix)
    return assessment

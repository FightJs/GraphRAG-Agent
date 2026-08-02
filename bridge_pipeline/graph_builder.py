"""
Knowledge Graph Builder: AnnotatedDocument → knowledge_graph.json
Constructs nodes and edges from LangExtract extraction results.

规范依据: bridgepipeline-spec-v1.0.md § 五·5.2
"""

import json
from typing import Dict, List, Any
from datetime import datetime
import langextract as lx


def build_knowledge_graph(
    annotated_docs: List,
    pdf_stem: str = "document",
    include_grounded_only: bool = False,
) -> Dict[str, Any]:
    """Build knowledge graph from AnnotatedDocument list.

    Args:
        annotated_docs: List of lx.data.AnnotatedDocument
        pdf_stem: PDF identifier for metadata
        include_grounded_only: Only include extractions with char_interval set

    Returns:
        Dict with keys: "nodes", "edges", "meta"

    规范: extraction_class 含 "实体_" → 节点; extraction_class == "关系" → 边
    """
    nodes: Dict[str, Dict[str, Any]] = {}  # {node_id: node_obj}
    edges: List[Dict[str, Any]] = []
    entity_count = 0
    relation_count = 0

    for doc in annotated_docs:
        if not hasattr(doc, "extractions"):
            continue

        for extraction in doc.extractions:
            extraction_class = extraction.extraction_class or ""
            extraction_text = extraction.extraction_text or ""
            attributes = extraction.attributes or {}
            char_interval = extraction.char_interval
            source_doc = doc.document_id if hasattr(doc, "document_id") else "unknown"

            # Skip if include_grounded_only and char_interval is None
            if include_grounded_only and char_interval is None:
                continue

            # Rule 1: extraction_class 含 "实体_" → 节点
            if "实体_" in extraction_class:
                node_id = extraction_text  # Use extraction_text as unique node ID
                if node_id not in nodes:
                    nodes[node_id] = {
                        "id": node_id,
                        "type": extraction_class,
                        "attributes": attributes,
                        "source_docs": [source_doc],
                        "occurrence_count": 1,
                    }
                    entity_count += 1
                else:
                    # Merge occurrences
                    if source_doc not in nodes[node_id]["source_docs"]:
                        nodes[node_id]["source_docs"].append(source_doc)
                    nodes[node_id]["occurrence_count"] += 1
                    # Merge attributes (deep merge)
                    for k, v in attributes.items():
                        if k not in nodes[node_id]["attributes"]:
                            nodes[node_id]["attributes"][k] = v

            # Rule 2: extraction_class == "关系" → 边
            elif extraction_class == "关系":
                source = attributes.get("主体", "")
                target = attributes.get("客体", "")
                relation_type = attributes.get("关系类型", "unknown")

                if source and target:
                    edges.append(
                        {
                            "source": source,
                            "target": target,
                            "relation": relation_type,
                            "text": extraction_text,  # Original text as evidence
                            "source_doc": source_doc,
                        }
                    )
                    relation_count += 1

    # Build final nodes list
    nodes_list = list(nodes.values())

    # Build metadata
    meta = {
        "source_pdf": pdf_stem,
        "total_nodes": len(nodes_list),
        "total_edges": len(edges),
        "entity_count": entity_count,
        "relation_count": relation_count,
        "created_at": datetime.utcnow().isoformat(),
    }

    return {
        "nodes": nodes_list,
        "edges": edges,
        "meta": meta,
    }


def save_knowledge_graph(
    graph: Dict[str, Any],
    output_path: str,
) -> None:
    """Save knowledge graph to JSON file.

    Args:
        graph: Knowledge graph dict (output of build_knowledge_graph)
        output_path: Path to save knowledge_graph.json
    """
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)


def load_knowledge_graph(path: str) -> Dict[str, Any]:
    """Load knowledge graph from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_graphs(*graphs: Dict[str, Any]) -> Dict[str, Any]:
    """Merge multiple knowledge graphs into one.

    Useful when processing multiple documents.
    """
    merged_nodes: Dict[str, Dict[str, Any]] = {}
    merged_edges: List[Dict[str, Any]] = []
    total_docs = 0

    for graph in graphs:
        # Merge nodes
        for node in graph.get("nodes", []):
            node_id = node.get("id")
            if node_id not in merged_nodes:
                merged_nodes[node_id] = node.copy()
                merged_nodes[node_id]["source_docs"] = list(node.get("source_docs", []))
                merged_nodes[node_id]["occurrence_count"] = node.get("occurrence_count", 1)
            else:
                # Merge occurrence
                existing = merged_nodes[node_id]
                existing["occurrence_count"] += node.get("occurrence_count", 1)
                for doc in node.get("source_docs", []):
                    if doc not in existing["source_docs"]:
                        existing["source_docs"].append(doc)
                # Merge attributes
                for k, v in node.get("attributes", ).items():
                    if k not in existing.get("attributes", {}):
                        existing["attributes"][k] = v

        # Merge edges
        merged_edges.extend(graph.get("edges", []))

        # Count docs
        total_docs += 1

    return {
        "nodes": list(merged_nodes.values()),
        "edges": merged_edges,
        "meta": {
            "total_nodes": len(merged_nodes),
            "total_edges": len(merged_edges),
            "total_documents": total_docs,
            "created_at": datetime.utcnow().isoformat(),
        },
    }

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trade_py.infra.settings.context import default_data_root

if TYPE_CHECKING:
    from trade_py.db.trade_db import TradeDB
else:
    TradeDB = Any

logger = logging.getLogger(__name__)

_DATA_ROOT = str(default_data_root())


@dataclass
class KGRunResult:
    summary: str
    exit_code: int = 0
    rows_processed: int | None = None


def _track_kg_run(
    data_root: str,
    job_name: str,
    runner,
    *,
    stage: str = "train",
) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(data_root)
    run_id = db.job_run_start(job_name, stage=stage)
    started = time.time()
    try:
        result = runner()
        elapsed_ms = int((time.time() - started) * 1000)
        status = "ok" if result.exit_code == 0 else "error"
        db.job_run_finish(
            run_id,
            status,
            result_summary=result.summary[:500],
            symbols_processed=result.rows_processed,
            elapsed_ms=elapsed_ms,
        )
        return result.exit_code
    except KeyboardInterrupt:
        elapsed_ms = int((time.time() - started) * 1000)
        db.job_run_finish(
            run_id,
            "error",
            result_summary="interrupted by user",
            elapsed_ms=elapsed_ms,
        )
        logger.warning("kg command interrupted job=%s", job_name)
        return 130
    except Exception as exc:
        elapsed_ms = int((time.time() - started) * 1000)
        db.job_run_finish(
            run_id,
            "error",
            result_summary=str(exc)[:500],
            elapsed_ms=elapsed_ms,
        )
        logger.error("kg command failed job=%s: %s", job_name, exc, exc_info=True)
        return 1


def make_parser() -> argparse.ArgumentParser:
    from trade_py.cli import epilog_from_subparsers, global_flag_parent

    parser = argparse.ArgumentParser(
        prog="trade kg",
        description="Learned KG 候选边学习 / 审核 / 上线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flag_parent()],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_learn = sub.add_parser("learn", description="从价格联动和事件数据生成 KG 候选边")
    p_learn.add_argument("--data-root", default=_DATA_ROOT)
    p_learn.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD，默认读 settings.kline.start")
    p_learn.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD，默认今天")
    p_learn.add_argument("--top-k", type=int, default=4, help="每个行业每个方向保留的 Top-K 边")
    p_learn.add_argument("--max-lag", type=int, default=3, help="最大传播滞后天数")
    p_learn.add_argument("--min-event-count", type=int, default=2, help="event_map 最小样本数")
    p_learn.add_argument("--min-samples", type=int, default=20, help="sector_link 最小重叠样本数")
    p_learn.add_argument("--min-confidence", type=float, default=0.25, help="最小置信度")
    p_learn.add_argument("--min-weight", type=float, default=0.12, help="最小边权")
    p_learn.add_argument("--backend", default="auto", choices=["auto", "lgbm", "xgboost", "catboost"], help="edge learner 后端")

    p_candidates = sub.add_parser("candidates", description="查看 KG 候选边")
    p_candidates.add_argument("--data-root", default=_DATA_ROOT)
    p_candidates.add_argument("--limit", type=int, default=30)
    p_candidates.add_argument("--status", default="pending",
                              help="pending|approved|promoted|rejected|disabled|all")
    p_candidates.add_argument("--rel-type", default=None)
    p_candidates.add_argument("--entity", default=None)

    p_evaluate = sub.add_parser("evaluate", description="汇总 active graph 与候选边研究状态")
    p_evaluate.add_argument("--data-root", default=_DATA_ROOT)
    p_evaluate.add_argument("--top", type=int, default=8, help="展示多少条高分候选边")

    p_review = sub.add_parser("review", description="给出推荐审核的候选边清单")
    p_review.add_argument("--data-root", default=_DATA_ROOT)
    p_review.add_argument("--status", default="pending", help="pending|approved|all")
    p_review.add_argument("--rel-type", default=None)
    p_review.add_argument("--source-prefix", default=None)
    p_review.add_argument("--limit", type=int, default=20)
    p_review.add_argument("--min-confidence", type=float, default=0.45)
    p_review.add_argument("--min-weight", type=float, default=0.18)
    p_review.add_argument("--min-samples", type=int, default=25)
    p_review.add_argument("--sort", default="confidence", choices=["confidence", "weight", "raw"])

    p_approve = sub.add_parser("approve", description="批准候选边")
    p_approve.add_argument("ids", nargs="+", type=int)
    p_approve.add_argument("--data-root", default=_DATA_ROOT)
    p_approve.add_argument("--reviewer", default="cli")
    p_approve.add_argument("--note", default="")
    p_approve.add_argument("--weight", type=float, default=None)

    p_reject = sub.add_parser("reject", description="拒绝候选边")
    p_reject.add_argument("ids", nargs="+", type=int)
    p_reject.add_argument("--data-root", default=_DATA_ROOT)
    p_reject.add_argument("--reviewer", default="cli")
    p_reject.add_argument("--note", default="")

    p_promote = sub.add_parser("promote", description="将已批准候选边写入 kg_relations")
    p_promote.add_argument("ids", nargs="*", type=int, help="留空则 promote 全部 approved 候选")
    p_promote.add_argument("--data-root", default=_DATA_ROOT)
    p_promote.add_argument("--valid-from", default=None)
    p_promote.add_argument("--valid-to", default=None)
    p_promote.add_argument("--source", default=None)
    p_promote.add_argument("--batch", default=None, choices=["approved", "recommended"],
                           help="按筛选规则批量 promote approved 候选")
    p_promote.add_argument("--limit", type=int, default=10)
    p_promote.add_argument("--rel-type", default=None)
    p_promote.add_argument("--source-prefix", default=None)
    p_promote.add_argument("--min-confidence", type=float, default=0.45)
    p_promote.add_argument("--min-weight", type=float, default=0.18)
    p_promote.add_argument("--min-samples", type=int, default=25)

    p_relations = sub.add_parser("relations", description="查看已上线 KG 边")
    p_relations.add_argument("--data-root", default=_DATA_ROOT)
    p_relations.add_argument("--limit", type=int, default=30)
    p_relations.add_argument("--rel-type", default=None)
    p_relations.add_argument("--entity", default=None)
    p_relations.add_argument("--all", action="store_true", help="包含 disabled / expired 关系")

    p_disable = sub.add_parser("disable", description="下线已上线 KG 边")
    p_disable.add_argument("from_entity")
    p_disable.add_argument("to_entity")
    p_disable.add_argument("rel_type")
    p_disable.add_argument("--data-root", default=_DATA_ROOT)

    p_nodes = sub.add_parser("nodes", description="查看 KG 节点")
    p_nodes.add_argument("--data-root", default=_DATA_ROOT)
    p_nodes.add_argument("--limit", type=int, default=50)
    p_nodes.add_argument("--entity-type", default=None)
    p_nodes.add_argument("--status", default="active", help="active|all")
    p_nodes.add_argument("--entity", default=None)

    p_snapshot = sub.add_parser("snapshot", description="构建或查看 KG active snapshot")
    p_snapshot.add_argument("--data-root", default=_DATA_ROOT)
    p_snapshot.add_argument("--build", action="store_true", help="重建 snapshot 文件")

    parser.epilog = epilog_from_subparsers(parser)
    return parser


def _cmd_learn(args: argparse.Namespace) -> int:
    from trade_py.intelligence.graph.learned import learn_kg_candidates

    def _runner() -> KGRunResult:
        summary = learn_kg_candidates(
            args.data_root,
            start=args.start,
            end=args.end,
            top_k=args.top_k,
            max_lag=args.max_lag,
            min_event_count=args.min_event_count,
            min_samples=args.min_samples,
            min_confidence=args.min_confidence,
            min_weight=args.min_weight,
            backend=args.backend,
        )
        text = summary.format()
        print(text)
        return KGRunResult(text, rows_processed=summary.total_candidates)

    return _track_kg_run(args.data_root, "kg_learn", _runner)


def _candidate_sort_key(row: dict, sort: str) -> tuple[float, float, float]:
    if sort == "weight":
        return (
            float(row.get("weight") or 0.0),
            float(row.get("confidence") or 0.0),
            float(row.get("raw_score") or 0.0),
        )
    if sort == "raw":
        return (
            float(row.get("raw_score") or 0.0),
            float(row.get("confidence") or 0.0),
            float(row.get("weight") or 0.0),
        )
    return (
        float(row.get("confidence") or 0.0),
        float(row.get("weight") or 0.0),
        float(row.get("raw_score") or 0.0),
    )


def _candidate_rows_for_review(
    db: TradeDB,
    *,
    status: str | None,
    rel_type: str | None,
    entity: str | None = None,
    source_prefix: str | None = None,
    min_confidence: float = 0.0,
    min_weight: float = 0.0,
    min_samples: int = 0,
    limit: int = 20,
    sort: str = "confidence",
) -> list[dict]:
    fetch_limit = max(limit * 25, 500)
    rows = db.kg_candidates(
        limit=fetch_limit,
        status=None if status == "all" else status,
        rel_type=rel_type,
        entity=entity,
    )
    filtered: list[dict] = []
    for row in rows:
        if source_prefix and not str(row.get("source") or "").startswith(source_prefix):
            continue
        if float(row.get("confidence") or 0.0) < float(min_confidence):
            continue
        if float(row.get("weight") or 0.0) < float(min_weight):
            continue
        if int(row.get("sample_count") or 0) < int(min_samples):
            continue
        filtered.append(row)
    filtered.sort(key=lambda item: _candidate_sort_key(item, sort), reverse=True)
    return filtered[:limit]


def _print_candidate_table(rows: list[dict]) -> None:
    if not rows:
        print("暂无候选边")
        return
    print(
        f"{'id':<5} {'status':<10} {'type':<12} {'from':<24} {'to':<24} "
        f"{'w':>6} {'conf':>6} {'n':>5} {'raw':>6} source"
    )
    print("-" * 132)
    for row in rows:
        print(
            f"{int(row['id']):<5} {str(row['status']):<10} {str(row['rel_type']):<12} "
            f"{str(row['from_entity']):<24} {str(row['to_entity']):<24} "
            f"{float(row['weight']):>6.3f} {float(row['confidence']):>6.3f} "
            f"{int(row['sample_count']):>5} {float(row.get('raw_score') or 0.0):>6.3f} "
            f"{str(row.get('source') or '')}"
        )


def _cmd_candidates(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    status = None if args.status == "all" else args.status
    rows = db.kg_candidates(
        limit=args.limit,
        status=status,
        rel_type=args.rel_type,
        entity=args.entity,
    )
    if not rows:
        print("暂无候选边")
        return 0
    _print_candidate_table(rows)
    return 0


def _cmd_evaluate(args: argparse.Namespace) -> int:
    from trade_py.analysis.knowledge_graph import SectorGraph

    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    active_summary = db._conn.execute(
        """
        SELECT rel_type, source, COUNT(*) AS edge_count,
               ROUND(AVG(weight), 4) AS avg_weight,
               ROUND(AVG(confidence), 4) AS avg_confidence
        FROM kg_relations
        WHERE status = 'active' AND (valid_to IS NULL OR valid_to >= date('now'))
        GROUP BY rel_type, source
        ORDER BY edge_count DESC, rel_type, source
        """
    ).fetchall()
    candidate_summary = db._conn.execute(
        """
        SELECT status, rel_type, source, COUNT(*) AS edge_count,
               ROUND(AVG(weight), 4) AS avg_weight,
               ROUND(AVG(confidence), 4) AS avg_confidence
        FROM kg_edge_candidates
        GROUP BY status, rel_type, source
        ORDER BY edge_count DESC, status, rel_type, source
        """
    ).fetchall()

    snapshot_path = SectorGraph.snapshot_path(args.data_root)
    snapshot_info = None
    if Path(snapshot_path).exists():
        payload = json.loads(Path(snapshot_path).read_text())
        snapshot_info = {
            "generated_at": payload.get("generated_at"),
            "nodes": len(payload.get("nodes", {})),
            "edges": len(payload.get("edges", [])),
            "event_mappings": len(payload.get("event_mappings", {})),
        }

    print("active_snapshot:")
    if snapshot_info:
        print(
            f"  generated_at={snapshot_info['generated_at']} nodes={snapshot_info['nodes']} "
            f"edges={snapshot_info['edges']} event_mappings={snapshot_info['event_mappings']}"
        )
    else:
        print("  missing")
    print()
    print("active_relations:")
    if not active_summary:
        print("  暂无 active KG 边")
    for row in active_summary:
        print(
            f"  {row['rel_type']:<12} source={str(row['source'] or ''):<32} "
            f"count={int(row['edge_count']):>4} avg_w={float(row['avg_weight'] or 0.0):.3f} "
            f"avg_conf={float(row['avg_confidence'] or 0.0):.3f}"
        )
    print()
    print("candidate_pool:")
    if not candidate_summary:
        print("  暂无候选边")
    for row in candidate_summary:
        print(
            f"  {row['status']:<10} {row['rel_type']:<12} source={str(row['source'] or ''):<32} "
            f"count={int(row['edge_count']):>4} avg_w={float(row['avg_weight'] or 0.0):.3f} "
            f"avg_conf={float(row['avg_confidence'] or 0.0):.3f}"
        )
    print()
    print("recommended_review:")
    rows = _candidate_rows_for_review(
        db,
        status="pending",
        rel_type=None,
        source_prefix=None,
        min_confidence=0.45,
        min_weight=0.18,
        min_samples=25,
        limit=args.top,
        sort="confidence",
    )
    _print_candidate_table(rows)
    if rows:
        ids = " ".join(str(row["id"]) for row in rows)
        print()
        print(f"建议审批: trade kg approve {ids}")
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    rows = _candidate_rows_for_review(
        db,
        status=args.status,
        rel_type=args.rel_type,
        source_prefix=args.source_prefix,
        min_confidence=args.min_confidence,
        min_weight=args.min_weight,
        min_samples=args.min_samples,
        limit=args.limit,
        sort=args.sort,
    )
    _print_candidate_table(rows)
    if rows:
        print()
        print("ids:", " ".join(str(row["id"]) for row in rows))
    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    changed = db.kg_candidate_review(
        args.ids,
        "approved",
        reviewer=args.reviewer,
        review_note=args.note,
        weight=args.weight,
    )
    print(f"已批准 {changed} 条候选边")
    return 0


def _cmd_reject(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    changed = db.kg_candidate_review(
        args.ids,
        "rejected",
        reviewer=args.reviewer,
        review_note=args.note,
    )
    print(f"已拒绝 {changed} 条候选边")
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    candidate_ids = list(args.ids or [])
    if not candidate_ids and (args.batch or args.rel_type or args.source_prefix):
        rows = _candidate_rows_for_review(
            db,
            status="approved",
            rel_type=args.rel_type,
            source_prefix=args.source_prefix,
            min_confidence=args.min_confidence,
            min_weight=args.min_weight,
            min_samples=args.min_samples,
            limit=args.limit,
            sort="confidence" if args.batch == "recommended" else "weight",
        )
        candidate_ids = [int(row["id"]) for row in rows]
    promoted = db.kg_promote_candidates(
        candidate_ids or None,
        valid_from=args.valid_from,
        valid_to=args.valid_to,
        source_override=args.source,
    )
    if promoted:
        from trade_py.analysis.knowledge_graph import SectorGraph

        path = SectorGraph.build_active_snapshot(args.data_root, merge_defaults=True)
        db.kg_node_upsert_batch(SectorGraph.load(path).to_registry_rows())
    print(f"已上线 {promoted} 条 KG 边")
    return 0


def _cmd_relations(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    rows = db.kg_relations_list(
        limit=args.limit,
        rel_type=args.rel_type,
        entity=args.entity,
        active_only=not args.all,
    )
    if not rows:
        print("暂无已上线 KG 边")
        return 0
    print(f"{'id':<5} {'status':<10} {'type':<12} {'from':<24} {'to':<24} {'dir':>4} {'lag':>4} {'w':>6} {'conf':>6}")
    print("-" * 108)
    for row in rows:
        print(
            f"{row['id']:<5} {row['status']:<10} {row['rel_type']:<12} "
            f"{row['from_entity']:<24} {row['to_entity']:<24} "
            f"{int(row['direction']):>4} {int(row['typical_days']):>4} "
            f"{float(row['weight']):>6.3f} {float(row['confidence']):>6.3f}"
        )
    return 0


def _cmd_disable(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    changed = db.kg_relation_disable(args.from_entity, args.to_entity, args.rel_type)
    if changed:
        from trade_py.analysis.knowledge_graph import SectorGraph

        path = SectorGraph.build_active_snapshot(args.data_root, merge_defaults=True)
        db.kg_node_upsert_batch(SectorGraph.load(path).to_registry_rows())
    print(f"已下线 {changed} 条 KG 边")
    return 0


def _cmd_nodes(args: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    rows = db.kg_nodes_list(
        limit=args.limit,
        entity_type=args.entity_type,
        status=None if args.status == "all" else args.status,
        entity=args.entity,
    )
    if not rows:
        print("暂无 KG 节点")
        return 0
    print(f"{'entity_id':<28} {'type':<12} {'status':<10} {'source':<20} name")
    print("-" * 96)
    for row in rows:
        print(
            f"{str(row['entity_id']):<28} {str(row['entity_type']):<12} "
            f"{str(row['status']):<10} {str(row.get('source') or ''):<20} "
            f"{str(row.get('display_name') or '')}"
        )
    return 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    from trade_py.analysis.knowledge_graph import SectorGraph

    from trade_py.db.trade_db import TradeDB
    db = TradeDB(args.data_root)
    if args.build:
        db.kg_rebuild_nodes()
        path = SectorGraph.build_active_snapshot(args.data_root, merge_defaults=True)
    else:
        path = SectorGraph.snapshot_path(args.data_root)
        if not path.exists():
            db.kg_rebuild_nodes()
            path = SectorGraph.build_active_snapshot(args.data_root, merge_defaults=True)
    graph = SectorGraph.load(path)
    db.kg_node_upsert_batch(graph.to_registry_rows())
    payload = graph.to_dict()
    print(f"path: {path}")
    print(f"nodes: {len(payload.get('nodes', []))}")
    print(f"edges: {len(payload.get('edges', []))}")
    print(f"event_mappings: {len(payload.get('event_mappings', {}))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    dispatch = {
        "learn": _cmd_learn,
        "candidates": _cmd_candidates,
        "evaluate": _cmd_evaluate,
        "review": _cmd_review,
        "approve": _cmd_approve,
        "reject": _cmd_reject,
        "promote": _cmd_promote,
        "relations": _cmd_relations,
        "disable": _cmd_disable,
        "nodes": _cmd_nodes,
        "snapshot": _cmd_snapshot,
    }
    return dispatch[args.command](args)

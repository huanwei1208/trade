"""KGCRUDMixin — CRUD for KG tables and market events.

Tables covered:
    kg_nodes, kg_relations, kg_edge_candidates,
    market_events, event_propagations

Mixed into TradeDB via multiple inheritance.
"""
from __future__ import annotations

import json
from typing import Any


def _infer_kg_node_type(entity_id: str | None, *, rel_type: str | None = None, role: str = "node") -> str:
    text = str(entity_id or "").strip()
    rel = str(rel_type or "").strip().lower()
    if not text:
        return "unknown"
    if rel == "event_map" and role == "from":
        return "event_type"
    if text.startswith("SW_"):
        return "sector"
    if text.endswith((".SH", ".SZ", ".BJ")):
        return "stock"
    if text.startswith(("IDX_", "INDEX_")):
        return "index"
    return "event_type" if rel == "event_map" else "unknown"


def _default_kg_node_name(entity_id: str | None, entity_type: str) -> str:
    text = str(entity_id or "").strip()
    if entity_type == "sector" and text.startswith("SW_"):
        return text[3:]
    return text


class KGCRUDMixin:
    """KG and market-event CRUD operations."""

    # ── Market Events ──────────────────────────────────────────────────────────

    def event_upsert(self, row: dict) -> None:
        """Upsert into market_events. Accepts both old 'events' schema and new schema."""
        mapped = dict(row)
        if "primary_sector" in mapped and "entity_id" not in mapped:
            mapped["entity_id"] = mapped.pop("primary_sector")
        if "actor_type" in mapped:
            mapped.pop("actor_type")

        cols = list(mapped.keys())
        placeholders = ", ".join(["?"] * len(cols))
        self._conn.execute(
            f"INSERT OR REPLACE INTO market_events ({', '.join(cols)}) VALUES ({placeholders})",
            [mapped[c] for c in cols],
        )
        self._conn.commit()

    def event_delete_range(self, start_date: str, end_date: str) -> tuple[int, int]:
        """Delete market_events and their propagation rows for a date range."""
        prop_cur = self._conn.execute(
            """
            DELETE FROM event_propagations
            WHERE event_id IN (
                SELECT event_id FROM market_events
                WHERE event_date >= ? AND event_date <= ?
            )
            """,
            (start_date, end_date),
        )
        event_cur = self._conn.execute(
            "DELETE FROM market_events WHERE event_date >= ? AND event_date <= ?",
            (start_date, end_date),
        )
        self._conn.execute(
            "DELETE FROM event_propagations WHERE event_id NOT IN (SELECT event_id FROM market_events)"
        )
        self._conn.commit()
        return int(event_cur.rowcount or 0), int(prop_cur.rowcount or 0)

    def event_cleanup_orphan_propagations(self) -> int:
        cur = self._conn.execute(
            "DELETE FROM event_propagations WHERE event_id NOT IN (SELECT event_id FROM market_events)"
        )
        self._conn.commit()
        return int(cur.rowcount or 0)

    def event_propagation_insert_batch(self, rows: list[dict]) -> None:
        if not rows:
            return
        table_cols = {
            r[1] for r in self._conn.execute("PRAGMA table_info(event_propagations)").fetchall()
        }
        clean_rows = []
        for r in rows:
            clean = {k: v for k, v in r.items() if k in table_cols}
            if "event_date" in table_cols and "event_date" not in clean:
                clean["event_date"] = r.get("event_date")
            if "sector" in table_cols and "sector" not in clean:
                clean["sector"] = r.get("sector")
            if "rel_path" in table_cols and "rel_path" not in clean and "path" in r:
                clean["rel_path"] = r.get("path")
            clean.setdefault("hop", 0)
            clean_rows.append(clean)
        cols = list(clean_rows[0].keys())
        placeholders = ", ".join(["?"] * len(cols))
        self._conn.executemany(
            f"INSERT OR IGNORE INTO event_propagations ({', '.join(cols)}) VALUES ({placeholders})",
            [[r[c] for c in cols] for r in clean_rows],
        )
        self._conn.commit()

    def get_events(
        self, from_date: str | None = None, to_date: str | None = None,
        event_type: str | None = None, failed_only: bool = False, limit: int = 1000,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if from_date:
            clauses.append("e.event_date >= ?"); params.append(from_date)
        if to_date:
            clauses.append("e.event_date <= ?"); params.append(to_date)
        if event_type:
            clauses.append("e.event_type = ?"); params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        having = "HAVING COUNT(ep.id) = 0" if failed_only else ""
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT e.event_id, e.event_date, e.event_type, e.magnitude,
                   e.entity_id AS primary_sector, e.breadth,
                   e.sentiment_score, e.news_volume, e.summary,
                   COUNT(ep.id) AS affected_stocks
            FROM market_events e
            LEFT JOIN event_propagations ep ON e.event_id = ep.event_id
            {where} GROUP BY e.event_id {having}
            ORDER BY e.event_date DESC LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def events_recent(self, limit: int = 30, symbol: str | None = None,
                      event_type: str | None = None) -> list[dict]:
        if symbol:
            rows = self._conn.execute(
                """
                SELECT e.event_id, e.event_date, e.event_type, e.magnitude,
                       e.entity_id AS primary_sector, e.breadth, e.summary,
                       ep.kg_score, ep.hop, ep.typical_days,
                       ep.actual_return_5d, ep.actual_return_20d
                FROM market_events e
                JOIN event_propagations ep ON e.event_id = ep.event_id
                WHERE ep.symbol = ? AND (? IS NULL OR e.event_type = ?)
                ORDER BY e.event_date DESC LIMIT ?
                """,
                (symbol, event_type, event_type, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT e.event_id, e.event_date, e.event_type, e.magnitude,
                       e.entity_id AS primary_sector, e.breadth, e.summary,
                       COUNT(ep.id) AS affected_stocks
                FROM market_events e
                LEFT JOIN event_propagations ep ON e.event_id = ep.event_id
                WHERE (? IS NULL OR e.event_type = ?)
                GROUP BY e.event_id ORDER BY e.event_date DESC LIMIT ?
                """,
                (event_type, event_type, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def event_propagations_fill_returns(self, event_date: str,
                                        symbol_returns: dict[str, float],
                                        window: int) -> int:
        col = f"actual_return_{window}d"
        updated = 0
        for symbol, ret in symbol_returns.items():
            cur = self._conn.execute(
                f"""UPDATE event_propagations SET {col} = ?,
                    validated_at = CASE WHEN actual_return_5d IS NOT NULL
                                        AND actual_return_20d IS NOT NULL
                                        THEN CURRENT_TIMESTAMP ELSE validated_at END
                    WHERE event_id IN (
                        SELECT event_id FROM market_events WHERE event_date = ?
                    ) AND symbol = ? AND {col} IS NULL""",
                (ret, event_date, symbol),
            )
            updated += cur.rowcount
        self._conn.commit()
        return updated

    # ── KG Nodes ───────────────────────────────────────────────────────────────

    def kg_node_upsert_batch(self, rows: list[dict]) -> None:
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT INTO kg_nodes (entity_id, entity_type, display_name, source, status, updated_at)
            VALUES (:entity_id, :entity_type, :display_name, :source, :status, CURRENT_TIMESTAMP)
            ON CONFLICT(entity_id) DO UPDATE SET
                entity_type=excluded.entity_type,
                display_name=excluded.display_name,
                source=excluded.source,
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP
            """,
            rows,
        )
        self._conn.commit()

    def kg_nodes_list(
        self,
        limit: int = 50,
        entity_type: str | None = None,
        status: str | None = "active",
        entity: str | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if entity_type:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if entity:
            clauses.append("entity_id = ?")
            params.append(entity)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            """
            SELECT entity_id, entity_type, display_name, source, status, updated_at
            FROM kg_nodes
            """ + where + """
            ORDER BY entity_type, entity_id
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def kg_rebuild_nodes(self) -> int:
        rows = self._conn.execute(
            """
            SELECT from_entity, to_entity, rel_type, source FROM kg_relations
            UNION ALL
            SELECT from_entity, to_entity, rel_type, source FROM kg_edge_candidates
            """
        ).fetchall()
        payload = self._kg_nodes_from_rows([dict(r) for r in rows])
        self.kg_node_upsert_batch(payload)
        return len(payload)

    def _kg_nodes_from_rows(self, rows: list[dict]) -> list[dict]:
        nodes: dict[str, dict] = {}
        for row in rows:
            rel_type = str(row.get("rel_type") or "")
            source = str(row.get("source") or "")
            for role, field in (("from", "from_entity"), ("to", "to_entity")):
                entity_id = str(row.get(field) or "").strip()
                if not entity_id:
                    continue
                entity_type = _infer_kg_node_type(entity_id, rel_type=rel_type, role=role)
                nodes[entity_id] = {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "display_name": _default_kg_node_name(entity_id, entity_type),
                    "source": source,
                    "status": "active",
                }
        return list(nodes.values())

    # ── KG Relations ───────────────────────────────────────────────────────────

    def kg_relation_upsert_batch(self, rows: list[dict]) -> None:
        """Batch upsert KG relations."""
        if not rows:
            return
        payload = []
        for row in rows:
            item = dict(row)
            item["weight"] = abs(float(item.get("weight", 0.0)))
            item["direction"] = int(item.get("direction", 1) or 1)
            item["typical_days"] = int(item.get("typical_days", 0) or 0)
            item["confidence"] = float(item.get("confidence", 0.0) or 0.0)
            item["sample_count"] = int(item.get("sample_count", 0) or 0)
            item["status"] = str(item.get("status", "active") or "active")
            evidence = item.get("evidence_json")
            if evidence is not None and not isinstance(evidence, str):
                item["evidence_json"] = json.dumps(evidence, ensure_ascii=False)
            payload.append(item)
        self.kg_node_upsert_batch(self._kg_nodes_from_rows(payload))
        self._conn.executemany(
            """
            INSERT INTO kg_relations
                (from_entity, to_entity, rel_type, weight, direction, typical_days,
                 confidence, sample_count, source, valid_from, valid_to,
                 evidence_json, status)
            VALUES (:from_entity, :to_entity, :rel_type,
                    :weight, :direction, :typical_days, :confidence,
                    :sample_count, :source, :valid_from, :valid_to,
                    :evidence_json, :status)
            ON CONFLICT(from_entity, to_entity, rel_type) DO UPDATE SET
                weight=excluded.weight,
                direction=excluded.direction,
                typical_days=excluded.typical_days,
                confidence=excluded.confidence,
                sample_count=excluded.sample_count,
                source=excluded.source,
                valid_from=excluded.valid_from,
                valid_to=excluded.valid_to,
                evidence_json=excluded.evidence_json,
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP
            """,
            payload,
        )
        self._conn.commit()

    def kg_neighbors(self, entity_id: str, rel_type: str | None = None,
                     active_only: bool = True) -> list[dict]:
        """Get direct neighbors of an entity in the KG."""
        clauses = ["from_entity = ?"]
        params: list = [entity_id]
        if rel_type:
            clauses.append("rel_type = ?")
            params.append(rel_type)
        if active_only:
            clauses.append("status = 'active'")
            clauses.append("(valid_to IS NULL OR valid_to >= date('now'))")
        where = " AND ".join(clauses)
        rows = self._conn.execute(
            """
            SELECT to_entity, rel_type, weight, direction, typical_days,
                   confidence, sample_count, source, evidence_json
            FROM kg_relations
            WHERE """ + where,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def kg_active_relations(self, rel_type: str | None = None) -> list[dict]:
        clauses = ["status = 'active'", "(valid_to IS NULL OR valid_to >= date('now'))"]
        params: list[Any] = []
        if rel_type:
            clauses.append("rel_type = ?")
            params.append(rel_type)
        rows = self._conn.execute(
            """
            SELECT id, from_entity, to_entity, rel_type, weight, direction,
                   typical_days, confidence, sample_count, source, valid_from,
                   valid_to, evidence_json, status
            FROM kg_relations
            WHERE """ + " AND ".join(clauses) + """
            ORDER BY rel_type, from_entity, ABS(weight) DESC, to_entity
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def kg_relations_list(
        self,
        limit: int = 50,
        rel_type: str | None = None,
        entity: str | None = None,
        active_only: bool = True,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if rel_type:
            clauses.append("rel_type = ?")
            params.append(rel_type)
        if entity:
            clauses.append("(from_entity = ? OR to_entity = ?)")
            params.extend([entity, entity])
        if active_only:
            clauses.append("status = 'active'")
            clauses.append("(valid_to IS NULL OR valid_to >= date('now'))")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            """
            SELECT id, from_entity, to_entity, rel_type, weight, direction,
                   typical_days, confidence, sample_count, source, valid_from,
                   valid_to, status
            FROM kg_relations
            """ + where + """
            ORDER BY ABS(weight) DESC, confidence DESC, id DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def kg_relation_disable(self, from_entity: str, to_entity: str,
                            rel_type: str) -> int:
        cur = self._conn.execute(
            """
            UPDATE kg_relations
            SET status = 'disabled',
                valid_to = COALESCE(valid_to, date('now')),
                updated_at = CURRENT_TIMESTAMP
            WHERE from_entity = ? AND to_entity = ? AND rel_type = ?
            """,
            (from_entity, to_entity, rel_type),
        )
        self._conn.commit()
        return int(cur.rowcount or 0)

    # ── KG Candidates ──────────────────────────────────────────────────────────

    def kg_candidate_upsert_batch(self, rows: list[dict]) -> None:
        if not rows:
            return
        payload = []
        for row in rows:
            item = dict(row)
            item["weight"] = abs(float(item.get("weight", 0.0)))
            item["direction"] = int(item.get("direction", 1) or 1)
            item["lag_days"] = int(item.get("lag_days", 0) or 0)
            item["confidence"] = float(item.get("confidence", 0.0) or 0.0)
            item["sample_count"] = int(item.get("sample_count", 0) or 0)
            item["price_link_score"] = float(item.get("price_link_score", 0.0) or 0.0)
            item["stability_score"] = float(item.get("stability_score", 0.0) or 0.0)
            item["event_support_score"] = float(item.get("event_support_score", 0.0) or 0.0)
            item["raw_score"] = float(item.get("raw_score", 0.0) or 0.0)
            item["status"] = str(item.get("status", "pending") or "pending")
            evidence = item.get("evidence_json")
            if evidence is not None and not isinstance(evidence, str):
                item["evidence_json"] = json.dumps(evidence, ensure_ascii=False)
            payload.append(item)
        self.kg_node_upsert_batch(self._kg_nodes_from_rows(payload))
        self._conn.executemany(
            """
            INSERT INTO kg_edge_candidates
                (from_entity, to_entity, rel_type, weight, direction, lag_days,
                 confidence, sample_count, price_link_score, stability_score,
                 event_support_score, raw_score, source, evidence_json, status)
            VALUES (:from_entity, :to_entity, :rel_type, :weight, :direction, :lag_days,
                    :confidence, :sample_count, :price_link_score, :stability_score,
                    :event_support_score, :raw_score, :source, :evidence_json, :status)
            ON CONFLICT(from_entity, to_entity, rel_type) DO UPDATE SET
                weight=excluded.weight,
                direction=excluded.direction,
                lag_days=excluded.lag_days,
                confidence=excluded.confidence,
                sample_count=excluded.sample_count,
                price_link_score=excluded.price_link_score,
                stability_score=excluded.stability_score,
                event_support_score=excluded.event_support_score,
                raw_score=excluded.raw_score,
                source=excluded.source,
                evidence_json=excluded.evidence_json,
                generated_at=CURRENT_TIMESTAMP,
                status=CASE
                    WHEN kg_edge_candidates.status IN ('approved', 'promoted', 'disabled')
                    THEN kg_edge_candidates.status
                    ELSE excluded.status
                END
            """,
            payload,
        )
        self._conn.commit()

    def kg_candidates(
        self,
        limit: int = 50,
        status: str | None = "pending",
        rel_type: str | None = None,
        entity: str | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if rel_type:
            clauses.append("rel_type = ?")
            params.append(rel_type)
        if entity:
            clauses.append("(from_entity = ? OR to_entity = ?)")
            params.extend([entity, entity])
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            """
            SELECT id, from_entity, to_entity, rel_type, weight, direction, lag_days,
                   confidence, sample_count, price_link_score, stability_score,
                   event_support_score, raw_score, source, status,
                   generated_at, reviewed_at, reviewer, review_note
            FROM kg_edge_candidates
            """ + where + """
            ORDER BY confidence DESC, ABS(weight) DESC, id DESC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]

    def kg_candidate_review(
        self,
        candidate_ids: list[int],
        status: str,
        *,
        reviewer: str | None = None,
        review_note: str | None = None,
        weight: float | None = None,
    ) -> int:
        if not candidate_ids:
            return 0
        placeholders = ", ".join("?" for _ in candidate_ids)
        params: list[Any] = [status, reviewer, review_note, abs(weight) if weight is not None else None]
        params.extend(candidate_ids)
        cur = self._conn.execute(
            f"""
            UPDATE kg_edge_candidates
            SET status = ?,
                reviewer = ?,
                review_note = ?,
                reviewed_at = CURRENT_TIMESTAMP,
                weight = COALESCE(?, weight)
            WHERE id IN ({placeholders})
            """,
            params,
        )
        self._conn.commit()
        return int(cur.rowcount or 0)

    def kg_promote_candidates(
        self,
        candidate_ids: list[int] | None = None,
        *,
        valid_from: str | None = None,
        valid_to: str | None = None,
        source_override: str | None = None,
    ) -> int:
        clauses = ["status = 'approved'"]
        params: list[Any] = []
        if candidate_ids:
            placeholders = ", ".join("?" for _ in candidate_ids)
            clauses.append(f"id IN ({placeholders})")
            params.extend(candidate_ids)
        rows = self._conn.execute(
            """
            SELECT id, from_entity, to_entity, rel_type, weight, direction,
                   lag_days, confidence, sample_count, source, evidence_json
            FROM kg_edge_candidates
            WHERE """ + " AND ".join(clauses),
            params,
        ).fetchall()
        if not rows:
            return 0
        self.kg_relation_upsert_batch([
            {
                "from_entity": r["from_entity"],
                "to_entity": r["to_entity"],
                "rel_type": r["rel_type"],
                "weight": r["weight"],
                "direction": r["direction"],
                "typical_days": r["lag_days"],
                "confidence": r["confidence"],
                "sample_count": r["sample_count"],
                "source": source_override or r["source"],
                "valid_from": valid_from,
                "valid_to": valid_to,
                "evidence_json": r["evidence_json"],
                "status": "active",
            }
            for r in rows
        ])
        promoted_ids = [int(r["id"]) for r in rows]
        placeholders = ", ".join("?" for _ in promoted_ids)
        self._conn.execute(
            f"""
            UPDATE kg_edge_candidates
            SET status = 'promoted',
                reviewed_at = CURRENT_TIMESTAMP
            WHERE id IN ({placeholders})
            """,
            promoted_ids,
        )
        self._conn.commit()
        return len(rows)

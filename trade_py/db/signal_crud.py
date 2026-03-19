"""SignalCRUDMixin — CRUD for signals, factors, model_registry, and evaluation tables.

Tables covered:
    signals, factors, factor_registry, model_registry,
    source_health_daily, source_eval_daily, event_eval_runs, model_eval_runs,
    dataset_snapshots, daily_quality_gate

Mixed into TradeDB via multiple inheritance.
"""
from __future__ import annotations

import json
from typing import Any


class SignalCRUDMixin:
    """Signal, factor, model-registry and evaluation-table CRUD."""

    # ── Signals ────────────────────────────────────────────────────────────────

    def signal_upsert(self, date: str, symbol: str, **fields: Any) -> None:
        cols = ["date", "symbol"] + list(fields.keys())
        placeholders = ", ".join(["?"] * len(cols))
        updates = ", ".join(f"{k} = excluded.{k}" for k in fields)
        values = [date, symbol] + [str(v) if v is not None else None for v in fields.values()]
        self._conn.execute(
            f"INSERT INTO signals ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(date, symbol) DO UPDATE SET {updates}, "
            f"updated_at = CURRENT_TIMESTAMP",
            values,
        )
        self._conn.commit()

    def signal_cache_upsert(self, date: str, symbol: str, **fields: Any) -> None:
        self.signal_upsert(date, symbol, **fields)

    def signal_get(self, date: str, order_by: str = "auto") -> list[dict]:
        if order_by == "model_score":
            sort_col = "model_score DESC NULLS LAST"
        elif order_by == "window_score":
            sort_col = "window_score DESC NULLS LAST"
        elif order_by == "event_kg_score":
            sort_col = "event_kg_score DESC NULLS LAST"
        else:
            sort_col = "COALESCE(model_score, -1) DESC, COALESCE(window_score, 0) DESC"
        rows = self._conn.execute(
            f"SELECT * FROM signals WHERE date = ? ORDER BY {sort_col}",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def signal_cache_get(self, date: str, order_by: str = "auto") -> list[dict]:
        return self.signal_get(date, order_by)

    def signal_suggest(
        self, limit: int = 20, by: str = "model_score", sector_limit: int = 3,
    ) -> list[dict]:
        col = by if by in ("model_score", "window_score", "event_kg_score") else "model_score"
        try:
            rows = self._conn.execute(
                f"""
                WITH latest AS (
                    SELECT symbol, MAX(date) AS max_date
                    FROM signals WHERE {col} IS NOT NULL GROUP BY symbol
                )
                SELECT sc.date, sc.symbol, sc.model_score, sc.model_risk,
                       sc.window_score, sc.event_kg_score, sc.event_type,
                       sc.net_sentiment,
                       COALESCE(i.industry, 255) AS industry
                FROM signals sc
                JOIN latest ON sc.symbol = latest.symbol AND sc.date = latest.max_date
                LEFT JOIN instruments i ON sc.symbol = i.symbol
                ORDER BY sc.{col} DESC LIMIT ?
                """,
                (limit * sector_limit,),
            ).fetchall()
        except Exception:
            rows = self._conn.execute(
                f"""
                WITH latest AS (
                    SELECT symbol, MAX(date) AS max_date
                    FROM signals WHERE {col} IS NOT NULL GROUP BY symbol
                )
                SELECT sc.date, sc.symbol, sc.model_score, sc.model_risk,
                       sc.window_score, sc.event_kg_score, sc.event_type,
                       sc.net_sentiment, 255 AS industry
                FROM signals sc
                JOIN latest ON sc.symbol = latest.symbol AND sc.date = latest.max_date
                ORDER BY sc.{col} DESC LIMIT ?
                """,
                (limit * sector_limit,),
            ).fetchall()
        sector_counts: dict[int, int] = {}
        result = []
        for r in rows:
            d = dict(r)
            ind = d.get("industry", 255)
            if sector_counts.get(ind, 0) >= sector_limit:
                continue
            sector_counts[ind] = sector_counts.get(ind, 0) + 1
            result.append(d)
            if len(result) >= limit:
                break
        return result

    def signal_cache_suggest(self, limit: int = 20, by: str = "model_score",
                              sector_limit: int = 3) -> list[dict]:
        return self.signal_suggest(limit, by, sector_limit)

    def pipeline_dag_get_by_job(self, job_name: str) -> dict[str, Any] | None:
        """Return the first pipeline_dag row for a given job_name."""
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT * FROM pipeline_dag WHERE job_name=? LIMIT 1",
                (job_name,),
            ).fetchone()
        return dict(row) if row else None

    def pipeline_dag_update_config(self, dag_id: int, config_json: str) -> None:
        """Update config_json for a pipeline_dag row."""
        with self._conn_lock:
            self._conn.execute(
                "UPDATE pipeline_dag SET config_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (config_json, dag_id),
            )
            self._conn.commit()

    def signal_recommend(self, limit: int = 20) -> dict:
        """Three-stage recommendation pipeline: recall → coarse rank → fine rank + delta."""
        from datetime import date, timedelta

        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        def _recall_by_col(col: str, top_n: int, threshold: float | None = None) -> list[dict]:
            where = f"sc.{col} IS NOT NULL"
            if threshold is not None:
                where += f" AND sc.{col} >= {threshold}"
            try:
                rows = self._conn.execute(f"""
                    WITH latest AS (
                        SELECT symbol, MAX(date) AS max_date
                        FROM signals WHERE {col} IS NOT NULL GROUP BY symbol
                    )
                    SELECT sc.date, sc.symbol, sc.model_score, sc.model_risk,
                           sc.window_score, sc.event_kg_score, sc.event_type,
                           sc.net_sentiment, sc.event_affected,
                           COALESCE(i.industry, 255) AS industry
                    FROM signals sc
                    JOIN latest ON sc.symbol = latest.symbol AND sc.date = latest.max_date
                    LEFT JOIN instruments i ON sc.symbol = i.symbol
                    WHERE {where}
                    ORDER BY sc.{col} DESC LIMIT ?
                """, (top_n,)).fetchall()
                return [dict(r) for r in rows]
            except Exception:
                return []

        model_pool = _recall_by_col("model_score", 200, 0.5)
        event_pool = _recall_by_col("event_kg_score", 300, 60.0)
        tech_pool = _recall_by_col("window_score", 200, 70.0)

        try:
            watch_syms = [
                r["symbol"] for r in self._conn.execute(
                    "SELECT symbol FROM watchlist WHERE active=1"
                ).fetchall()
            ]
        except Exception:
            watch_syms = []

        all_syms: dict[str, dict] = {}
        for pool in [model_pool, event_pool, tech_pool]:
            for r in pool:
                all_syms.setdefault(str(r.get("symbol") or ""), r)
        for sym in watch_syms:
            if sym not in all_syms:
                try:
                    row = self._conn.execute("""
                        WITH latest AS (
                            SELECT symbol, MAX(date) AS max_date FROM signals GROUP BY symbol
                        )
                        SELECT sc.*, COALESCE(i.industry, 255) AS industry
                        FROM signals sc
                        JOIN latest ON sc.symbol = latest.symbol AND sc.date = latest.max_date
                        LEFT JOIN instruments i ON sc.symbol = i.symbol
                        WHERE sc.symbol = ? LIMIT 1
                    """, (sym,)).fetchone()
                    if row:
                        all_syms[sym] = dict(row)
                except Exception:
                    pass

        def _coarse_score(r: dict) -> float:
            return (
                0.4 * float(r.get("model_score") or 0.0)
                + 0.3 * float(r.get("window_score") or 0.0) / 100.0
                + 0.3 * float(r.get("event_kg_score") or 0.0) / 100.0
            )

        coarse = [r for r in all_syms.values() if float(r.get("net_sentiment") or 0.0) >= -0.5]
        coarse.sort(key=_coarse_score, reverse=True)
        coarse = coarse[:50]

        try:
            yest_syms = {
                str(row["symbol"]) for row in self._conn.execute(
                    "SELECT symbol FROM signals WHERE date=? "
                    "ORDER BY COALESCE(model_score, 0) DESC LIMIT 50",
                    (yesterday,)
                ).fetchall()
            }
        except Exception:
            yest_syms = set()

        result = []
        for r in coarse[:limit]:
            sym = str(r.get("symbol") or "")
            coarse_s = round(_coarse_score(r), 4)
            result.append({
                "symbol": sym,
                "date": r.get("date", today),
                "coarse_score": coarse_s,
                "model_score": r.get("model_score"),
                "window_score": r.get("window_score"),
                "event_kg_score": r.get("event_kg_score"),
                "net_sentiment": r.get("net_sentiment"),
                "event_type": r.get("event_type"),
                "industry": r.get("industry", 255),
                "is_new": sym not in yest_syms,
            })

        return {
            "date": today,
            "picks": result,
            "pool_sizes": {
                "model": len(model_pool),
                "event": len(event_pool),
                "tech": len(tech_pool),
                "watchlist": len(watch_syms),
            },
        }

    # ── Factors ────────────────────────────────────────────────────────────────

    def factor_upsert_batch(self, rows: list[dict]) -> None:
        """Batch upsert factor rows. Each row: date, symbol, factor_name, factor_type, value."""
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT INTO factors (date, symbol, factor_name, factor_type, value, updated_at)
            VALUES (:date, :symbol, :factor_name, :factor_type, :value, CURRENT_TIMESTAMP)
            ON CONFLICT(date, symbol, factor_name) DO UPDATE SET
                factor_type=excluded.factor_type,
                value=excluded.value,
                updated_at=CURRENT_TIMESTAMP
            """,
            rows,
        )
        self._conn.commit()

    def factor_registry_upsert_batch(self, rows: list[dict]) -> None:
        """Register factor definitions. Each row: factor_name, factor_type, factor_layer, description, source."""
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT INTO factor_registry (factor_name, factor_type, factor_layer, description, source, updated_at)
            VALUES (:factor_name, :factor_type, :factor_layer, :description, :source, CURRENT_TIMESTAMP)
            ON CONFLICT(factor_name) DO UPDATE SET
                factor_type=excluded.factor_type,
                factor_layer=excluded.factor_layer,
                description=excluded.description,
                source=excluded.source,
                updated_at=CURRENT_TIMESTAMP
            """,
            rows,
        )
        self._conn.commit()

    def factor_registry_list(
        self,
        factor_type: str | None = None,
        factor_layer: str | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if factor_type:
            clauses.append("factor_type = ?")
            params.append(factor_type)
        if factor_layer:
            clauses.append("factor_layer = ?")
            params.append(factor_layer)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            """
            SELECT factor_name, factor_type, factor_layer, description, source, updated_at
            FROM factor_registry
            """ + where + """
            ORDER BY factor_type, factor_name
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def factor_reclassify_by_name(self, mapping: dict[str, str]) -> int:
        """Backfill factor_type based on factor_name -> factor_type mapping."""
        if not mapping:
            return 0
        cur = self._conn.cursor()
        total = 0
        for factor_name, factor_type in mapping.items():
            cur.execute(
                "UPDATE factors SET factor_type=?, updated_at=CURRENT_TIMESTAMP WHERE factor_name=?",
                (factor_type, factor_name),
            )
            total += int(cur.rowcount or 0)
        self._conn.commit()
        return total

    def factor_get_latest(self, symbol: str, factor_names: list[str] | None = None) -> dict:
        """Get latest factor values for a symbol. Returns {factor_name: value}."""
        if factor_names:
            placeholders = ",".join(["?"] * len(factor_names))
            rows = self._conn.execute(
                f"""
                WITH latest AS (
                    SELECT factor_name, MAX(date) AS max_date
                    FROM factors WHERE symbol=? AND factor_name IN ({placeholders})
                    GROUP BY factor_name
                )
                SELECT f.factor_name, f.value
                FROM factors f
                JOIN latest ON f.factor_name=latest.factor_name AND f.date=latest.max_date
                WHERE f.symbol=?
                """,
                [symbol] + factor_names + [symbol],
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                WITH latest AS (
                    SELECT factor_name, MAX(date) AS max_date
                    FROM factors WHERE symbol=? GROUP BY factor_name
                )
                SELECT f.factor_name, f.value
                FROM factors f
                JOIN latest ON f.factor_name=latest.factor_name AND f.date=latest.max_date
                WHERE f.symbol=?
                """,
                (symbol, symbol),
            ).fetchall()
        return {r["factor_name"]: r["value"] for r in rows}

    # ── Model Registry ─────────────────────────────────────────────────────────

    def model_registry_insert(
        self,
        model_name: str,
        model_type: str,
        file_path: str,
        metrics: dict | None = None,
        *,
        target_name: str | None = None,
        backend: str | None = None,
        artifact_format: str | None = None,
        feature_set: str | None = None,
        dataset_snapshot_id: int | None = None,
        promotion_state: str = "active",
        activate: bool | None = None,
    ) -> int:
        target_name = target_name or model_name
        promotion_state = promotion_state or "active"
        if activate is None:
            activate = promotion_state == "active"

        if activate:
            self._conn.execute(
                "UPDATE model_registry SET is_active=0, promotion_state='retired' WHERE target_name=? AND is_active=1",
                (target_name,),
            )
        cur = self._conn.execute(
            """
            INSERT INTO model_registry
                (model_name, target_name, model_type, backend, artifact_format,
                 file_path, feature_set, dataset_snapshot_id, metrics, is_active, promotion_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_name,
                target_name,
                model_type,
                backend or ("tabular_nn" if "onnx" in (artifact_format or model_type or "").lower() else "lgbm"),
                artifact_format or ("onnx" if str(file_path).lower().endswith(".onnx") else "joblib"),
                file_path,
                feature_set,
                dataset_snapshot_id,
                json.dumps(metrics) if metrics else None,
                1 if activate else 0,
                "active" if activate else promotion_state,
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def model_registry_get_active(self, model_name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM model_registry WHERE (target_name=? OR model_name=?) AND is_active=1 "
            "ORDER BY trained_at DESC LIMIT 1",
            (model_name, model_name),
        ).fetchone()
        if row is None:
            return None
        r = dict(row)
        if r.get("metrics"):
            try:
                r["metrics"] = json.loads(r["metrics"])
            except Exception:
                pass
        return r

    def model_registry_get(self, model_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM model_registry WHERE id=?",
            (int(model_id),),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("metrics"):
            try:
                result["metrics"] = json.loads(result["metrics"])
            except Exception:
                pass
        return result

    def model_registry_list(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM model_registry ORDER BY trained_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("metrics"):
                try:
                    d["metrics"] = json.loads(d["metrics"])
                except Exception:
                    pass
            result.append(d)
        return result

    def model_registry_promote(self, model_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM model_registry WHERE id=?",
            (int(model_id),),
        ).fetchone()
        if row is None:
            return None
        target_name = str(row["target_name"] or row["model_name"])
        self._conn.execute(
            "UPDATE model_registry SET is_active=0, promotion_state='retired' WHERE target_name=? AND is_active=1",
            (target_name,),
        )
        self._conn.execute(
            "UPDATE model_registry SET is_active=1, promotion_state='active' WHERE id=?",
            (int(model_id),),
        )
        self._conn.commit()
        return self.model_registry_get_active(target_name)

    # ── Evaluation: Source Health ──────────────────────────────────────────────

    def source_health_upsert_batch(self, rows: list[dict]) -> None:
        if not rows:
            return
        payload = []
        for row in rows:
            item = dict(row)
            details = item.get("details_json")
            if details is not None and not isinstance(details, str):
                item["details_json"] = json.dumps(details, ensure_ascii=False)
            payload.append(item)
        self._conn.executemany(
            """
            INSERT INTO source_health_daily
                (eval_date, source_name, source_family, provider_kind,
                 bronze_days, article_rows, unique_articles, duplicate_rate,
                 empty_day_rate, ingest_runs, ingest_error_rate,
                 records_fetched, records_new, healthy, details_json, updated_at)
            VALUES (:eval_date, :source_name, :source_family, :provider_kind,
                    :bronze_days, :article_rows, :unique_articles, :duplicate_rate,
                    :empty_day_rate, :ingest_runs, :ingest_error_rate,
                    :records_fetched, :records_new, :healthy, :details_json,
                    CURRENT_TIMESTAMP)
            ON CONFLICT(eval_date, source_name) DO UPDATE SET
                source_family=excluded.source_family,
                provider_kind=excluded.provider_kind,
                bronze_days=excluded.bronze_days,
                article_rows=excluded.article_rows,
                unique_articles=excluded.unique_articles,
                duplicate_rate=excluded.duplicate_rate,
                empty_day_rate=excluded.empty_day_rate,
                ingest_runs=excluded.ingest_runs,
                ingest_error_rate=excluded.ingest_error_rate,
                records_fetched=excluded.records_fetched,
                records_new=excluded.records_new,
                healthy=excluded.healthy,
                details_json=excluded.details_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            payload,
        )
        self._conn.commit()

    def source_eval_upsert_batch(self, rows: list[dict]) -> None:
        if not rows:
            return
        payload = []
        for row in rows:
            item = dict(row)
            details = item.get("details_json")
            if details is not None and not isinstance(details, str):
                item["details_json"] = json.dumps(details, ensure_ascii=False)
            payload.append(item)
        self._conn.executemany(
            """
            INSERT INTO source_eval_daily
                (eval_date, source_name, source_family, provider_kind,
                 silver_rows, event_rows, event_yield_per_100,
                 labeled_rows, rank_ic_5d, details_json, updated_at)
            VALUES (:eval_date, :source_name, :source_family, :provider_kind,
                    :silver_rows, :event_rows, :event_yield_per_100,
                    :labeled_rows, :rank_ic_5d, :details_json, CURRENT_TIMESTAMP)
            ON CONFLICT(eval_date, source_name) DO UPDATE SET
                source_family=excluded.source_family,
                provider_kind=excluded.provider_kind,
                silver_rows=excluded.silver_rows,
                event_rows=excluded.event_rows,
                event_yield_per_100=excluded.event_yield_per_100,
                labeled_rows=excluded.labeled_rows,
                rank_ic_5d=excluded.rank_ic_5d,
                details_json=excluded.details_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            payload,
        )
        self._conn.commit()

    def source_health_list(self, eval_date: str | None = None) -> list[dict]:
        if eval_date:
            rows = self._conn.execute(
                "SELECT * FROM source_health_daily WHERE eval_date=? ORDER BY healthy DESC, article_rows DESC, source_name",
                (eval_date,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT sh.*
                FROM source_health_daily sh
                JOIN (
                    SELECT MAX(eval_date) AS eval_date FROM source_health_daily
                ) latest ON sh.eval_date = latest.eval_date
                ORDER BY sh.healthy DESC, sh.article_rows DESC, sh.source_name
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def source_eval_list(self, eval_date: str | None = None) -> list[dict]:
        if eval_date:
            rows = self._conn.execute(
                "SELECT * FROM source_eval_daily WHERE eval_date=? ORDER BY COALESCE(rank_ic_5d, -99) DESC, event_yield_per_100 DESC, source_name",
                (eval_date,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT se.*
                FROM source_eval_daily se
                JOIN (
                    SELECT MAX(eval_date) AS eval_date FROM source_eval_daily
                ) latest ON se.eval_date = latest.eval_date
                ORDER BY COALESCE(se.rank_ic_5d, -99) DESC, se.event_yield_per_100 DESC, se.source_name
                """
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Evaluation: Event Eval ─────────────────────────────────────────────────

    def event_eval_upsert(self, row: dict) -> None:
        payload = dict(row)
        details = payload.get("details_json")
        if details is not None and not isinstance(details, str):
            payload["details_json"] = json.dumps(details, ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO event_eval_runs
                (eval_date, start_date, end_date, status, event_count,
                 effective_event_rate, sw_unknown_ratio, propagations_per_event,
                 labeled_propagation_ratio, avg_actual_return_5d,
                 avg_actual_return_20d, details_json, created_at)
            VALUES (:eval_date, :start_date, :end_date, :status, :event_count,
                    :effective_event_rate, :sw_unknown_ratio, :propagations_per_event,
                    :labeled_propagation_ratio, :avg_actual_return_5d,
                    :avg_actual_return_20d, :details_json, CURRENT_TIMESTAMP)
            ON CONFLICT(eval_date, start_date, end_date) DO UPDATE SET
                status=excluded.status,
                event_count=excluded.event_count,
                effective_event_rate=excluded.effective_event_rate,
                sw_unknown_ratio=excluded.sw_unknown_ratio,
                propagations_per_event=excluded.propagations_per_event,
                labeled_propagation_ratio=excluded.labeled_propagation_ratio,
                avg_actual_return_5d=excluded.avg_actual_return_5d,
                avg_actual_return_20d=excluded.avg_actual_return_20d,
                details_json=excluded.details_json,
                created_at=CURRENT_TIMESTAMP
            """,
            payload,
        )
        self._conn.commit()

    def event_eval_latest(self, eval_date: str | None = None) -> dict | None:
        if eval_date:
            row = self._conn.execute(
                "SELECT * FROM event_eval_runs WHERE eval_date=? ORDER BY id DESC LIMIT 1",
                (eval_date,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM event_eval_runs ORDER BY eval_date DESC, id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("details_json"):
            try:
                result["details_json"] = json.loads(result["details_json"])
            except Exception:
                pass
        return result

    def event_eval_get(self, eval_date: str, start_date: str, end_date: str) -> dict | None:
        row = self._conn.execute(
            """
            SELECT * FROM event_eval_runs
            WHERE eval_date=? AND start_date=? AND end_date=?
            ORDER BY id DESC LIMIT 1
            """,
            (eval_date, start_date, end_date),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("details_json"):
            try:
                result["details_json"] = json.loads(result["details_json"])
            except Exception:
                pass
        return result

    # ── Evaluation: Model Eval ─────────────────────────────────────────────────

    def model_eval_upsert(self, row: dict) -> None:
        payload = dict(row)
        for key in ("baseline_json", "calibration_json", "details_json"):
            value = payload.get(key)
            if value is not None and not isinstance(value, str):
                payload[key] = json.dumps(value, ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO model_eval_runs
                (eval_date, model_name, target_name, model_version, status,
                 sample_count, valid_days, rank_ic, mae, topk_hit_rate,
                 sector_concentration, risk_brier_score, baseline_json,
                 calibration_json, details_json, created_at)
            VALUES (:eval_date, :model_name, :target_name, :model_version, :status,
                    :sample_count, :valid_days, :rank_ic, :mae, :topk_hit_rate,
                    :sector_concentration, :risk_brier_score, :baseline_json,
                    :calibration_json, :details_json, CURRENT_TIMESTAMP)
            ON CONFLICT(eval_date, model_name, target_name) DO UPDATE SET
                model_version=excluded.model_version,
                status=excluded.status,
                sample_count=excluded.sample_count,
                valid_days=excluded.valid_days,
                rank_ic=excluded.rank_ic,
                mae=excluded.mae,
                topk_hit_rate=excluded.topk_hit_rate,
                sector_concentration=excluded.sector_concentration,
                risk_brier_score=excluded.risk_brier_score,
                baseline_json=excluded.baseline_json,
                calibration_json=excluded.calibration_json,
                details_json=excluded.details_json,
                created_at=CURRENT_TIMESTAMP
            """,
            payload,
        )
        self._conn.commit()

    def model_eval_list(self, eval_date: str | None = None, model_name: str | None = None) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if eval_date:
            clauses.append("eval_date=?")
            params.append(eval_date)
        if model_name:
            clauses.append("model_name=?")
            params.append(model_name)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        if not where:
            where = "WHERE eval_date = (SELECT MAX(eval_date) FROM model_eval_runs)"
        rows = self._conn.execute(
            f"SELECT * FROM model_eval_runs {where} ORDER BY model_name, target_name",
            params,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in ("baseline_json", "calibration_json", "details_json"):
                if item.get(key):
                    try:
                        item[key] = json.loads(item[key])
                    except Exception:
                        pass
            result.append(item)
        return result

    # ── Evaluation: Dataset Snapshots ──────────────────────────────────────────

    def dataset_snapshot_upsert(self, row: dict) -> None:
        payload = dict(row)
        metadata = payload.get("metadata_json")
        if metadata is not None and not isinstance(metadata, str):
            payload["metadata_json"] = json.dumps(metadata, ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO dataset_snapshots
                (snapshot_name, eval_date, start_date, end_date, source_count,
                 market_event_count, propagation_count, feature_rows,
                 labeled_rows_5d, labeled_rows_20d, signal_dates,
                 metadata_json, created_at)
            VALUES (:snapshot_name, :eval_date, :start_date, :end_date, :source_count,
                    :market_event_count, :propagation_count, :feature_rows,
                    :labeled_rows_5d, :labeled_rows_20d, :signal_dates,
                    :metadata_json, CURRENT_TIMESTAMP)
            ON CONFLICT(snapshot_name, eval_date) DO UPDATE SET
                start_date=excluded.start_date,
                end_date=excluded.end_date,
                source_count=excluded.source_count,
                market_event_count=excluded.market_event_count,
                propagation_count=excluded.propagation_count,
                feature_rows=excluded.feature_rows,
                labeled_rows_5d=excluded.labeled_rows_5d,
                labeled_rows_20d=excluded.labeled_rows_20d,
                signal_dates=excluded.signal_dates,
                metadata_json=excluded.metadata_json,
                created_at=CURRENT_TIMESTAMP
            """,
            payload,
        )
        self._conn.commit()

    def dataset_snapshot_get(self, eval_date: str | None = None,
                             snapshot_name: str = "daily") -> dict | None:
        if eval_date:
            row = self._conn.execute(
                """
                SELECT * FROM dataset_snapshots
                WHERE snapshot_name=? AND eval_date=?
                ORDER BY id DESC LIMIT 1
                """,
                (snapshot_name, eval_date),
            ).fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT * FROM dataset_snapshots
                WHERE snapshot_name=?
                ORDER BY eval_date DESC, id DESC LIMIT 1
                """,
                (snapshot_name,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result.get("metadata_json"):
            try:
                result["metadata_json"] = json.loads(result["metadata_json"])
            except Exception:
                pass
        return result

    # ── Evaluation: Quality Gate ───────────────────────────────────────────────

    def quality_gate_upsert(self, eval_date: str, status: str,
                            reasons: list[str], metrics: dict | None = None) -> None:
        reason_summary = "; ".join(reasons[:5]) if reasons else ""
        self._conn.execute(
            """
            INSERT INTO daily_quality_gate
                (eval_date, status, reason_summary, reasons_json, metrics_json, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(eval_date) DO UPDATE SET
                status=excluded.status,
                reason_summary=excluded.reason_summary,
                reasons_json=excluded.reasons_json,
                metrics_json=excluded.metrics_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                eval_date,
                status,
                reason_summary,
                json.dumps(reasons, ensure_ascii=False),
                json.dumps(metrics or {}, ensure_ascii=False),
            ),
        )
        self._conn.commit()

    def quality_gate_get(self, eval_date: str | None = None) -> dict | None:
        if eval_date:
            row = self._conn.execute(
                "SELECT * FROM daily_quality_gate WHERE eval_date=?",
                (eval_date,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT * FROM daily_quality_gate ORDER BY eval_date DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for key in ("reasons_json", "metrics_json"):
            if result.get(key):
                try:
                    result[key] = json.loads(result[key])
                except Exception:
                    pass
        return result

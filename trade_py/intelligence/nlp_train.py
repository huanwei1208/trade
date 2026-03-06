"""NLP model training and ONNX export (offline, Python-only).

This module handles:
1. Fine-tuning FinBERT-Chinese / RoBERTa-wwm on financial sentiment data
2. Exporting trained models to ONNX format for C++ inference

Usage:
    python -m trade_py.nlp_train --base-model yiyanghkust/finbert-tone-chinese \
        --train-data data/raw/sentiment/bronze/ \
        --output data/models/sentiment/finbert_zh.onnx
"""

import argparse
from pathlib import Path


def finetune_sentiment(
    base_model: str = "yiyanghkust/finbert-tone-chinese",
    train_data: str = "data/raw/sentiment/",
    output_onnx: str = "data/models/sentiment/finbert_zh.onnx",
    epochs: int = 3,
    batch_size: int = 16,
    learning_rate: float = 2e-5,
    max_length: int = 128,
    lookback_days: int = 30,
):
    """Fine-tune a Chinese financial sentiment model and export to ONNX.

    Args:
        base_model: HuggingFace model name/path
        train_data: Path to training data (Bronze layer parquet files)
        output_onnx: Output ONNX model path
        epochs: Number of training epochs
        batch_size: Training batch size
        learning_rate: Learning rate
        max_length: Maximum sequence length
    """
    try:
        import torch
        from transformers import (
            AutoTokenizer,
            AutoModelForSequenceClassification,
            TrainingArguments,
            Trainer,
        )
    except ImportError:
        raise ImportError(
            "PyTorch and Transformers required for NLP training:\n"
            "  pip install torch transformers"
        )

    print(f"Fine-tuning {base_model}")
    print(f"Training data: {train_data}")
    print(f"Output: {output_onnx}")

    # Load tokenizer and model
    tokenizer = AutoTokenizer.from_pretrained(base_model)
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model, num_labels=3  # positive, neutral, negative
    )

    # --- 1. Load labeled training data (Bronze ⨝ Silver on content_hash) ---
    import pandas as _pd
    from datetime import date as _date, timedelta as _td
    from torch.utils.data import Dataset as _TorchDataset

    bronze_root = Path(train_data)
    # Silver lives at data/sentiment/silver/ (two levels up from raw/sentiment/)
    data_root = bronze_root.parent.parent
    silver_base = data_root / "sentiment" / "silver"

    cutoff_date = _date.today() - _td(days=lookback_days)

    def _recent(p: Path) -> bool:
        """Return True if parquet file stem is a date within the lookback window."""
        try:
            return _date.fromisoformat(p.stem) >= cutoff_date
        except ValueError:
            return True  # keep files whose names are not pure dates

    bronze_files = [f for f in bronze_root.rglob("*.parquet") if _recent(f)]
    if not bronze_files:
        raise FileNotFoundError(
            f"No Bronze parquet files found in {train_data} "
            f"(lookback_days={lookback_days})"
        )

    bronze_dfs: list[_pd.DataFrame] = []
    for f in bronze_files:
        try:
            df = _pd.read_parquet(f)
            keep_cols = [c for c in ["content_hash", "title", "text"] if c in df.columns]
            bronze_dfs.append(df[keep_cols])
        except Exception:
            pass
    bronze_df = _pd.concat(bronze_dfs, ignore_index=True).dropna(subset=["content_hash"])

    silver_files = (
        [f for f in silver_base.rglob("*.parquet") if _recent(f)]
        if silver_base.exists()
        else []
    )
    silver_parts: list[_pd.DataFrame] = []
    for f in silver_files:
        try:
            sdf = _pd.read_parquet(f)
            label_col = (
                "sentiment_label" if "sentiment_label" in sdf.columns
                else "sentiment" if "sentiment" in sdf.columns
                else None
            )
            if "content_hash" in sdf.columns and label_col:
                silver_parts.append(
                    sdf[["content_hash", label_col]].rename(
                        columns={label_col: "sentiment_label"}
                    )
                )
        except Exception:
            pass

    silver_df = (
        _pd.concat(silver_parts, ignore_index=True).drop_duplicates("content_hash")
        if silver_parts
        else _pd.DataFrame(columns=["content_hash", "sentiment_label"])
    )

    labeled = bronze_df.merge(silver_df, on="content_hash", how="inner")
    labeled = labeled[labeled["sentiment_label"].isin(["positive", "neutral", "negative"])]
    _LABEL_MAP = {"positive": 0, "neutral": 1, "negative": 2}
    labeled["label"] = labeled["sentiment_label"].map(_LABEL_MAP)
    labeled["input_text"] = (
        labeled.get("title", _pd.Series("", index=labeled.index)).fillna("")
        + " "
        + labeled.get("text", _pd.Series("", index=labeled.index)).fillna("")
    ).str.strip()
    labeled = labeled[labeled["input_text"].str.len() > 0].reset_index(drop=True)

    dist = labeled["sentiment_label"].value_counts().to_dict()
    print(f"Loaded {len(labeled)} labeled samples: {dist}")

    # --- 2. Fine-tune model ---
    if len(labeled) == 0:
        print("WARNING: No labeled samples found — exporting untrained base model.")
    else:
        class _SentimentDataset(_TorchDataset):
            def __init__(self, texts: list[str], labels: list[int]) -> None:
                enc = tokenizer(
                    texts,
                    truncation=True,
                    padding="max_length",
                    max_length=max_length,
                )
                self._input_ids = torch.tensor(enc["input_ids"])
                self._attn_mask = torch.tensor(enc["attention_mask"])
                self._labels = torch.tensor(labels, dtype=torch.long)

            def __len__(self) -> int:
                return len(self._labels)

            def __getitem__(self, idx):
                return {
                    "input_ids": self._input_ids[idx],
                    "attention_mask": self._attn_mask[idx],
                    "labels": self._labels[idx],
                }

        train_dataset = _SentimentDataset(
            labeled["input_text"].tolist(),
            labeled["label"].tolist(),
        )
        training_args = TrainingArguments(
            output_dir=str(Path(output_onnx).parent / "trainer_output"),
            num_train_epochs=epochs,
            per_device_train_batch_size=batch_size,
            learning_rate=learning_rate,
            save_strategy="no",
            logging_steps=50,
            no_cuda=not torch.cuda.is_available(),
        )
        trainer = Trainer(model=model, args=training_args, train_dataset=train_dataset)
        trainer.train()
        print(f"Training complete: {epochs} epoch(s), {len(labeled)} samples")

    # Export to ONNX
    output_path = Path(output_onnx)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    dummy_input = tokenizer(
        "这是一个测试句子", return_tensors="pt",
        max_length=max_length, padding="max_length", truncation=True
    )

    torch.onnx.export(
        model,
        (dummy_input["input_ids"], dummy_input["attention_mask"]),
        str(output_path),
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch_size"},
            "attention_mask": {0: "batch_size"},
            "logits": {0: "batch_size"},
        },
        opset_version=14,
    )

    # Also save tokenizer config for C++ loading
    tokenizer.save_pretrained(str(output_path.parent))

    print(f"Model exported to {output_onnx}")
    print(f"Tokenizer saved to {output_path.parent}")


def main():
    parser = argparse.ArgumentParser(description="Train sentiment NLP model")
    parser.add_argument("--base-model", default="yiyanghkust/finbert-tone-chinese")
    parser.add_argument("--train-data", default="data/raw/sentiment/")
    parser.add_argument("--output", default="data/models/sentiment/finbert_zh.onnx")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--lookback", type=int, default=30)
    args = parser.parse_args()

    finetune_sentiment(
        base_model=args.base_model,
        train_data=args.train_data,
        output_onnx=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        lookback_days=args.lookback,
    )


if __name__ == "__main__":
    main()

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
    train_data: str = "data/raw/sentiment/bronze/",
    output_onnx: str = "data/models/sentiment/finbert_zh.onnx",
    epochs: int = 3,
    batch_size: int = 16,
    learning_rate: float = 2e-5,
    max_length: int = 128,
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

    # TODO: Load and preprocess training data from Bronze parquet files
    # For now, placeholder
    print("TODO: Load training data from parquet Bronze layer")
    print("TODO: Train model")
    print("TODO: Export to ONNX")

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
    parser.add_argument("--train-data", default="data/raw/sentiment/bronze/")
    parser.add_argument("--output", default="data/models/sentiment/finbert_zh.onnx")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    args = parser.parse_args()

    finetune_sentiment(
        base_model=args.base_model,
        train_data=args.train_data,
        output_onnx=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
    )


if __name__ == "__main__":
    main()

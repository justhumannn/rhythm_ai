from __future__ import annotations

import torch
from torch import nn


class ChartGenerator(nn.Module):
    """Small CRNN baseline for frame-wise 4B chart prediction."""

    def __init__(
        self,
        *,
        n_mels: int = 96,
        hidden_size: int = 192,
        output_size: int = 8,
        dropout: float = 0.15,
        difficulty_count: int = 0,
    ) -> None:
        super().__init__()
        self.difficulty_count = difficulty_count
        self.encoder = nn.Sequential(
            nn.Conv1d(n_mels, 128, kernel_size=5, padding=2),
            nn.BatchNorm1d(128),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Conv1d(128, hidden_size, kernel_size=5, padding=2),
            nn.BatchNorm1d(hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
        )
        self.difficulty_embedding = (
            nn.Embedding(difficulty_count, hidden_size)
            if difficulty_count > 0
            else None
        )
        self.temporal = nn.GRU(
            input_size=hidden_size,
            hidden_size=hidden_size,
            num_layers=2,
            batch_first=True,
            bidirectional=True,
            dropout=dropout,
        )
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_size * 2),
            nn.Linear(hidden_size * 2, hidden_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, output_size),
        )

    def forward(
        self,
        features: torch.Tensor,
        difficulty: torch.Tensor | None = None,
    ) -> torch.Tensor:
        encoded = self.encoder(features)
        encoded = encoded.transpose(1, 2)
        if self.difficulty_embedding is not None:
            if difficulty is None:
                raise ValueError("difficulty is required by this checkpoint")
            condition = self.difficulty_embedding(difficulty.long()).unsqueeze(1)
            encoded = encoded + condition
        temporal, _ = self.temporal(encoded)
        return self.head(temporal)

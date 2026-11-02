"""Make models/tone/ser.mm8.onnx (tone of voice, sanae/tone.py) from audeering's wav2vec2 model.

The model is only published for PyTorch, so setup.ps1 runs this once in a throwaway environment
with torch + transformers: export to ONNX, then int8 for the matrix multiplications only (full
int8 was 4x slower on this CPU; MatMul-only is ~130 ms per command and within 0.01 of fp32).
Model licence: CC BY-NC-SA 4.0 (personal, non-commercial use).
Usage: python export_tone.py <out_dir>
"""
import sys
from pathlib import Path

import torch
import torch.nn as nn
from transformers import Wav2Vec2Model, Wav2Vec2PreTrainedModel

REPO = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)


class RegressionHead(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.dense = nn.Linear(config.hidden_size, config.hidden_size)
        self.dropout = nn.Dropout(config.final_dropout)
        self.out_proj = nn.Linear(config.hidden_size, config.num_labels)

    def forward(self, features):
        x = self.dropout(features)
        x = torch.tanh(self.dense(x))
        x = self.dropout(x)
        return self.out_proj(x)


class EmotionModel(Wav2Vec2PreTrainedModel):
    def __init__(self, config):
        super().__init__(config)
        self.config = config
        self.wav2vec2 = Wav2Vec2Model(config)
        self.classifier = RegressionHead(config)
        self.post_init()

    def forward(self, input_values):
        hidden = self.wav2vec2(input_values)[0]
        pooled = torch.mean(hidden, dim=1)
        return self.classifier(pooled)


model = EmotionModel.from_pretrained(REPO).eval()
print("labels:", model.config.id2label)
x = torch.zeros(1, 16000 * 3)
torch.onnx.export(model, (x,), str(out / "ser.onnx"), input_names=["input_values"], output_names=["adv"],
                  dynamic_axes={"input_values": {1: "samples"}}, opset_version=17, dynamo=False)
from onnxruntime.quantization import QuantType, quantize_dynamic  # noqa: E402

quantize_dynamic(str(out / "ser.onnx"), str(out / "ser.mm8.onnx"), weight_type=QuantType.QInt8,
                 op_types_to_quantize=["MatMul"])
(out / "ser.onnx").unlink()
print("ser.mm8.onnx", (out / "ser.mm8.onnx").stat().st_size // 1_000_000, "MB")

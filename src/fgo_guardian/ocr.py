from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Protocol

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class OCRResult:
    text: str
    confidence: float


class OCREngine(Protocol):
    def read(self, image: np.ndarray, *, whitelist: str | None = None) -> OCRResult: ...


class NullOCREngine:
    """Deterministic no-op engine for tests and template-only operation."""

    def read(self, image: np.ndarray, *, whitelist: str | None = None) -> OCRResult:
        del image, whitelist
        return OCRResult("", 0.0)


class TesseractOCREngine:
    """Small local Tesseract adapter that never sends images off the machine."""

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        language: str = "eng",
        page_segmentation_mode: int = 7,
        timeout_seconds: float = 5.0,
    ) -> None:
        candidate = str(executable) if executable is not None else shutil.which("tesseract")
        if not candidate and os.name == "nt":
            program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            common_install = program_files / "Tesseract-OCR" / "tesseract.exe"
            if common_install.is_file():
                candidate = str(common_install)
        if not candidate:
            raise FileNotFoundError("local Tesseract executable was not found")
        if not 0 <= page_segmentation_mode <= 13:
            raise ValueError("Tesseract page segmentation mode must be between 0 and 13")
        if timeout_seconds <= 0:
            raise ValueError("OCR timeout must be positive")
        self._executable = candidate
        self._language = language
        self._psm = page_segmentation_mode
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _encode(image: np.ndarray) -> bytes:
        if image.ndim == 3 and image.shape[2] == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        elif image.ndim == 2:
            gray = image
        else:
            raise ValueError("OCR expects an RGB or grayscale image")
        enlarged = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        encoded, png = cv2.imencode(".png", binary)
        if not encoded:
            raise RuntimeError("failed to encode OCR region")
        return png.tobytes()

    @staticmethod
    def _parse_tsv(output: str) -> OCRResult:
        words: list[str] = []
        confidences: list[float] = []
        lines = output.splitlines()
        if not lines:
            return OCRResult("", 0.0)
        columns = lines[0].split("\t")
        try:
            text_index = columns.index("text")
            confidence_index = columns.index("conf")
        except ValueError as error:
            raise RuntimeError("Tesseract returned an invalid TSV header") from error
        for line in lines[1:]:
            values = line.split("\t")
            if max(text_index, confidence_index) >= len(values):
                continue
            word = " ".join(values[text_index].split())
            if not word:
                continue
            try:
                confidence = float(values[confidence_index])
            except ValueError:
                continue
            if confidence < 0:
                continue
            words.append(word)
            confidences.append(confidence / 100.0)
        if not words:
            return OCRResult("", 0.0)
        return OCRResult(" ".join(words), sum(confidences) / len(confidences))

    def read(self, image: np.ndarray, *, whitelist: str | None = None) -> OCRResult:
        command = [
            self._executable,
            "stdin",
            "stdout",
            "-l",
            self._language,
            "--psm",
            str(self._psm),
            "tsv",
        ]
        if whitelist:
            command.extend(["-c", f"tessedit_char_whitelist={whitelist}"])
        environment = os.environ.copy()
        environment["OMP_THREAD_LIMIT"] = "1"
        completed = subprocess.run(
            command,
            input=self._encode(image),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self._timeout_seconds,
            check=False,
            env=environment,
        )
        if completed.returncode != 0:
            message = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Tesseract failed: {message or completed.returncode}")
        return self._parse_tsv(completed.stdout.decode("utf-8", errors="replace"))

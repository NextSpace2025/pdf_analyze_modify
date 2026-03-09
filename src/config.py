"""설정 파일 및 CLI 인자 로드."""
from pathlib import Path
from typing import Optional

import yaml


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"}
SUPPORTED_PDF_EXTENSIONS = {".pdf"}
SUPPORTED_EXTENSIONS = SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_PDF_EXTENSIONS

DEFAULT_OCR_LANG = "kor+eng"


def load_config(config_path: Path) -> dict:
    """YAML 설정 파일 로드."""
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError):
        return {}


def get_keywords(config: dict) -> list[str]:
    """설정에서 블랙리스트 키워드 목록 반환."""
    return list(config.get("keywords") or [])


def get_quarantine_dir(config: dict, default: str = "./quarantine") -> Path:
    """설정에서 격리 폴더 경로 반환."""
    raw = config.get("quarantine_dir") or default
    return Path(raw).resolve()


def get_ocr_lang(config: dict) -> str:
    """설정에서 OCR 언어 반환."""
    return config.get("ocr_lang") or DEFAULT_OCR_LANG


def collect_files(scan_path: Path, extensions: Optional[set[str]] = None) -> list[Path]:
    """스캔 경로에서 지원 확장자 파일 목록 수집 (비재귀)."""
    ext = extensions or SUPPORTED_EXTENSIONS
    if not scan_path.is_dir():
        return []
    return [p for p in scan_path.iterdir() if p.is_file() and p.suffix.lower() in ext]

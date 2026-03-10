"""이미지/PDF에서 Pytesseract OCR로 텍스트 추출. 팩스·저화질 스캔용 전처리 포함."""
import os
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path
from urllib import request

import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# 내장 텍스트가 이 글자 수 이상이면 OCR 생략
MIN_EMBEDDED_TEXT_LEN = 15

LOCAL_TESSDATA_DIR = Path("config/tessdata")
# Backward compatible path (older code used config/tessdata/tessdata)
LOCAL_TESSDATA_DIR_LEGACY = Path("config/tessdata/tessdata")
TESSDATA_FAST_BASE = "https://github.com/tesseract-ocr/tessdata_fast/raw/main"


def _iter_tesseract_candidates() -> list[Path]:
    """환경 변수/PATH/Windows 기본 경로를 기준으로 Tesseract 후보 경로 수집."""
    raw_candidates: list[str] = []

    env_cmd = os.environ.get("TESSERACT_CMD") or os.environ.get("PYTESSERACT_TESSERACT_CMD")
    if env_cmd:
        raw_candidates.append(env_cmd)

    current_cmd = str(getattr(pytesseract.pytesseract, "tesseract_cmd", "") or "")
    if current_cmd and current_cmd.lower() != "tesseract":
        raw_candidates.append(current_cmd)

    which_cmd = shutil.which("tesseract")
    if which_cmd:
        raw_candidates.append(which_cmd)

    if os.name == "nt":
        raw_candidates.extend(
            [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
        )
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            raw_candidates.append(
                str(Path(local_appdata) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
            )

    candidates: list[Path] = []
    seen: set[str] = set()
    for raw in raw_candidates:
        if not raw:
            continue
        cleaned = raw.strip().strip('"').strip("'")
        if not cleaned:
            continue
        p = Path(cleaned).expanduser()
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(p)
    return candidates


def _configure_tesseract_cmd() -> Path | None:
    """실행 가능한 Tesseract 경로를 찾아 pytesseract에 설정."""
    for candidate in _iter_tesseract_candidates():
        if candidate.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return candidate
    return None


def _iter_local_tessdata_dirs() -> list[Path]:
    dirs: list[Path] = []
    if LOCAL_TESSDATA_DIR.exists():
        dirs.append(LOCAL_TESSDATA_DIR)
    if LOCAL_TESSDATA_DIR_LEGACY.exists() and LOCAL_TESSDATA_DIR_LEGACY not in dirs:
        dirs.append(LOCAL_TESSDATA_DIR_LEGACY)
    return dirs


def _local_langs(dir_path: Path) -> set[str]:
    try:
        return {p.stem for p in dir_path.glob("*.traineddata") if p.is_file()}
    except OSError:
        return set()


def _select_tessdata_dir_for_lang(lang_value: str) -> Path | None:
    """로컬 tessdata에 요청 언어가 모두 있으면 그 디렉토리를 사용."""
    codes = [c.strip() for c in (lang_value or "").split("+") if c.strip()]
    if not codes:
        return None
    for d in _iter_local_tessdata_dirs():
        langs = _local_langs(d)
        if all(code in langs for code in codes):
            return d
    return None


def _ensure_lang_data(lang_code: str) -> tuple[bool, str]:
    """traineddata를 로컬(config/tessdata)에 설치."""
    if _configure_tesseract_cmd() is None:
        return False, "Tesseract not found."

    code = (lang_code or "").strip()
    if not code:
        return False, "Language code is empty."

    LOCAL_TESSDATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = LOCAL_TESSDATA_DIR / f"{code}.traineddata"
    if dest.exists() and dest.stat().st_size > 1024 * 50:
        _available_tesseract_langs.cache_clear()
        return True, "Already installed."

    url = f"{TESSDATA_FAST_BASE}/{code}.traineddata"
    try:
        with request.urlopen(url, timeout=30) as resp:
            data = resp.read()
        if not data or len(data) < 1024 * 50:
            return False, "Downloaded file is too small."
        dest.write_bytes(data)
        _available_tesseract_langs.cache_clear()
        return True, f"Installed to {dest}"
    except Exception as exc:
        msg = str(exc).strip() or type(exc).__name__
        return False, f"Download failed: {msg}"


def check_tesseract(lang: str = "kor+eng") -> str | None:
    """Tesseract 설치 확인. 정상이면 None, 문제 시 오류 메시지 반환."""
    if _configure_tesseract_cmd() is None:
        return (
            "Tesseract OCR 엔진을 찾을 수 없습니다.\n\n"
            "설치 방법 (Windows):\n"
            "1. https://github.com/UB-Mannheim/tesseract/wiki 에서 다운로드\n"
            "2. 설치 시 'Additional language data' 에서 Korean 체크\n"
            "3. 설치 후 PC 재시작 또는 PATH에 Tesseract 폴더 추가\n"
            "4. 또는 TESSERACT_CMD 환경변수에 tesseract.exe 전체 경로 설정"
        )

    try:
        ver = pytesseract.get_tesseract_version()
        langs = set(pytesseract.get_languages())
        requested_langs = [code.strip() for code in lang.split("+") if code.strip()]
        missing_langs = [code for code in requested_langs if code not in langs]
        if missing_langs:
            missing_text = ", ".join(missing_langs)
            return (
                f"Tesseract {ver} 설치됨. 하지만 요청 언어 데이터({missing_text})가 없습니다.\n"
                "Tesseract 설치 시 언어팩을 선택하거나 tessdata에 traineddata를 추가하세요.\n"
                "다운로드: https://github.com/tesseract-ocr/tessdata"
            )
        return None
    except pytesseract.TesseractNotFoundError:
        return (
            "Tesseract OCR 엔진이 설치되어 있지 않거나 실행 경로가 잘못되었습니다.\n\n"
            "설치 방법 (Windows):\n"
            "1. https://github.com/UB-Mannheim/tesseract/wiki 에서 다운로드\n"
            "2. 설치 시 'Additional language data' 에서 Korean 체크\n"
            "3. 설치 후 PC 재시작 또는 PATH에 Tesseract 폴더 추가\n"
            "4. 또는 TESSERACT_CMD 환경변수에 tesseract.exe 전체 경로 설정"
        )


@lru_cache(maxsize=1)
def _available_tesseract_langs() -> set[str]:
    _configure_tesseract_cmd()
    try:
        return set(pytesseract.get_languages())
    except Exception:
        return set()


def has_lang_data(lang_code: str) -> bool:
    code = (lang_code or "").strip()
    if not code:
        return False
    if code in _available_tesseract_langs():
        return True
    for d in _iter_local_tessdata_dirs():
        if code in _local_langs(d):
            return True
    return False


def _resolve_ocr_lang_and_tessdata_dir(requested: str) -> tuple[str, Path | None]:
    """요청 언어 중, 같은 tessdata 디렉토리에서 충족 가능한 것만 사용."""
    req = [code.strip() for code in (requested or "").split("+") if code.strip()]
    if not req:
        return "eng", None

    # Prefer local tessdata when it has any requested languages.
    for d in _iter_local_tessdata_dirs():
        langs = _local_langs(d)
        keep = [code for code in req if code in langs]
        if keep:
            return "+".join(keep), d

    # Fall back to system tessdata.
    sys_langs = _available_tesseract_langs()
    keep = [code for code in req if code in sys_langs]
    if keep:
        return "+".join(keep), None
    return "eng", None


def _resolve_ocr_lang(requested: str) -> str:
    """요청 언어(kor+eng 등) 중 설치된 언어만 사용. 없으면 eng로 폴백."""
    lang, _ = _resolve_ocr_lang_and_tessdata_dir(requested)
    return lang


# 팩스/저화질 스캔에서 OCR 정확도 향상을 위한 DPI
PDF_DPI = 300
# 전처리 후 최소 권장 너비(픽셀). 이보다 작으면 2배 확대
MIN_SIDE = 1200


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """팩스·저화질 이미지를 OCR에 유리하게 전처리."""
    if img.mode != "L":
        img = img.convert("L")
    w, h = img.size
    if max(w, h) < MIN_SIDE:
        scale = MIN_SIDE / max(w, h)
        nw, nh = int(w * scale), int(h * scale)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.5)
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(1.1)
    return img


def _ocr_image(img: Image.Image, lang: str = "kor+eng") -> str:
    """PIL 이미지에 전처리 적용 후 Tesseract OCR 수행. 실패 시 대비 강화 후 재시도."""
    _configure_tesseract_cmd()
    processed = _preprocess_for_ocr(img)
    use_lang, tessdata_dir = _resolve_ocr_lang_and_tessdata_dir(lang)
    config = "--psm 6 --oem 3"
    if tessdata_dir is not None:
        # pytesseract 내부에서 shlex.split을 사용할 때 Windows 백슬래시 경로가 깨질 수 있어,
        # tesseract가 문제없이 이해하는 슬래시 경로로 전달한다.
        tessdata_arg = tessdata_dir.resolve().as_posix()
        # Windows에서 config 문자열의 따옴표가 그대로 전달되어 경로에 포함되는 케이스가 있어
        # 공백이 없는 경로는 따옴표 없이 전달한다.
        config = f"{config} --tessdata-dir {tessdata_arg}"

    text = pytesseract.image_to_string(processed, lang=use_lang, config=config).strip() or ""
    if text:
        return text
    enh = ImageEnhance.Contrast(processed)
    stronger = enh.enhance(2.0)
    return pytesseract.image_to_string(stronger, lang=use_lang, config=config).strip() or ""


def extract_text_from_image(
    image_path: Path,
    lang: str = "kor+eng",
) -> str:
    """이미지 파일에서 OCR로 텍스트 추출."""
    img = Image.open(image_path)
    img.load()
    return _ocr_image(img, lang=lang)


def _extract_embedded_text(pdf_path: Path) -> str:
    """PDF 내장 텍스트만 추출 (이미지 OCR 없음). 텍스트가 없거나 적으면 빈 문자열에 가깝게 반환."""
    if fitz is None:
        return ""
    try:
        doc = fitz.open(pdf_path)
        parts = [page.get_text() for page in doc]
        doc.close()
        return "\n".join(parts).strip() if parts else ""
    except Exception:
        return ""


def extract_text_from_pdf(
    pdf_path: Path,
    lang: str = "kor+eng",
    dpi: int = PDF_DPI,
) -> str:
    """PDF에서 텍스트 추출. 내장 텍스트가 있으면 사용하고, 없거나 적으면 OCR 사용."""
    if fitz is not None:
        embedded = _extract_embedded_text(pdf_path)
        if len(embedded.strip()) >= MIN_EMBEDDED_TEXT_LEN:
            return embedded

    # OCR path:
    # Prefer PyMuPDF rendering to avoid poppler dependency (pdf2image).
    images: list[Image.Image]
    if fitz is not None:
        images = []
        doc = fitz.open(pdf_path)
        try:
            zoom = max(1.0, float(dpi) / 72.0)
            mat = fitz.Matrix(zoom, zoom)
            for i in range(doc.page_count):
                page = doc.load_page(i)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
        finally:
            doc.close()
    else:
        images = convert_from_path(str(pdf_path), dpi=dpi)

    parts = []
    for img in images:
        text = _ocr_image(img, lang=lang)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else ""


def _is_network_path(file_path: Path) -> bool:
    """UNC/네트워크 경로인지 여부."""
    s = str(file_path)
    return s.startswith("\\\\") or s.startswith("//")


def _copy_to_temp(file_path: Path) -> Path:
    """네트워크 파일을 로컬 임시 폴더에 복사해 반환."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="pdf_reader_"))
    dest = tmp_dir / file_path.name
    shutil.copy2(str(file_path), str(dest))
    return dest


def extract_text(
    file_path: Path,
    lang: str = "kor+eng",
) -> str:
    """파일 확장자에 따라 이미지 또는 PDF에서 텍스트 추출.
    네트워크 경로(UNC)는 로컬 임시 복사 후 처리."""
    local_path = file_path
    tmp_dir = None
    if _is_network_path(file_path):
        local_path = _copy_to_temp(file_path)
        tmp_dir = local_path.parent
    try:
        suffix = local_path.suffix.lower()
        if suffix == ".pdf":
            return extract_text_from_pdf(local_path, lang=lang)
        return extract_text_from_image(local_path, lang=lang)
    finally:
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

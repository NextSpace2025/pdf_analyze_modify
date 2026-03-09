"""이미지/PDF에서 Pytesseract OCR로 텍스트 추출. 팩스·저화질 스캔용 전처리 포함."""
import shutil
import tempfile
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# 내장 텍스트가 이 글자 수 이상이면 OCR 생략
MIN_EMBEDDED_TEXT_LEN = 15


def check_tesseract() -> str | None:
    """Tesseract 설치 확인. 정상이면 None, 문제 시 오류 메시지 반환."""
    try:
        ver = pytesseract.get_tesseract_version()
        langs = pytesseract.get_languages()
        if "kor" not in langs:
            return (
                f"Tesseract {ver} 설치됨. 하지만 한국어(kor) 언어팩이 없습니다.\n"
                "Tesseract 설치 폴더의 tessdata에 kor.traineddata를 추가하세요.\n"
                "다운로드: https://github.com/tesseract-ocr/tessdata"
            )
        return None
    except pytesseract.TesseractNotFoundError:
        return (
            "Tesseract OCR 엔진이 설치되어 있지 않거나 PATH에 없습니다.\n\n"
            "설치 방법 (Windows):\n"
            "1. https://github.com/UB-Mannheim/tesseract/wiki 에서 다운로드\n"
            "2. 설치 시 'Additional language data' 에서 Korean 체크\n"
            "3. 설치 후 PC 재시작 또는 PATH에 Tesseract 폴더 추가"
        )


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
    processed = _preprocess_for_ocr(img)
    config = "--psm 6 --oem 3"
    text = pytesseract.image_to_string(processed, lang=lang, config=config).strip() or ""
    if text:
        return text
    enh = ImageEnhance.Contrast(processed)
    stronger = enh.enhance(2.0)
    return pytesseract.image_to_string(stronger, lang=lang, config=config).strip() or ""


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

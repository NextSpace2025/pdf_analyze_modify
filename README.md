# pdf_analyze_modify

PDF 폴더를 분석하고, 텍스트 추출 결과(사유)에 따라 파일명을 일괄 변경·삭제할 수 있는 로컬 GUI 도구입니다.

## 요구 사항

- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) 설치
- PDF 사용 시 [Poppler](https://poppler.freedesktop.org/) 또는 `pdf2image` 환경 (Windows에서 사용 가능)

## 설치

```bash
pip install -r requirements.txt
```

## 실행 (로컬 GUI)

```bash
python app.py
```

1. **PDF 폴더 경로**를 입력하거나 **찾아보기**로 선택한 뒤 **분석**을 누르면, 해당 폴더의 PDF 목록과 각 파일의 내용 미리보기·분석 사유가 표시됩니다.
2. **파일명 바꾸기** / **삭제(휴지통)** 로 개별 처리할 수 있습니다.
3. **사유 기반 일괄 변경**: 분석 사유(정상 추출, 추출 실패 등)에 따라 규칙(접두사)을 지정하면, 해당 규칙에 맞게 파일명이 일괄 변경됩니다.

## CLI (스팸 필터)

`config/keywords.yaml`에서 블랙리스트 키워드와 격리 폴더를 설정한 뒤:

```bash
python main.py ./대상폴더
python main.py ./대상폴더 --use-trash   # 휴지통으로 이동
python main.py ./대상폴더 --dry-run     # 이동 없이 스팸 목록만 출력
```

## 프로젝트 구조

```
pdf_reader/
├── src/
│   ├── config.py       # 설정 로드
│   ├── ocr.py          # 이미지/PDF 텍스트 추출
│   ├── naming_api.py   # 사유 기반 파일명 규칙 API
│   ├── spam_checker.py # 블랙리스트 매칭
│   └── file_handler.py # 격리/휴지통 이동
├── config/
│   └── keywords.yaml
├── app.py              # 로컬 GUI (Tkinter)
├── main.py             # CLI
└── requirements.txt
```

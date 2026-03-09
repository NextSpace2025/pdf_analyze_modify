"""CLI 진입점: 스캔 경로에서 PDF/이미지 OCR 후 스팸이면 격리 또는 휴지통으로 이동."""
import argparse
import sys
from pathlib import Path

from src.config import (
    SUPPORTED_EXTENSIONS,
    collect_files,
    get_keywords,
    get_ocr_lang,
    get_quarantine_dir,
    load_config,
)
from src.file_handler import move_to_quarantine, move_to_trash
from src.ocr import extract_text
from src.spam_checker import is_spam


def parse_args():
    parser = argparse.ArgumentParser(
        description="PDF/이미지에서 OCR로 텍스트 추출 후 블랙리스트 키워드 포함 시 스팸으로 이동"
    )
    parser.add_argument(
        "scan_path",
        type=Path,
        help="스캔할 폴더 경로",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config/keywords.yaml"),
        help="설정 파일 경로 (기본: config/keywords.yaml)",
    )
    parser.add_argument(
        "-q",
        "--quarantine-dir",
        type=Path,
        default=None,
        help="격리 폴더 (설정 파일보다 우선)",
    )
    parser.add_argument(
        "--use-trash",
        action="store_true",
        help="격리 대신 휴지통으로 이동",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="이동 없이 스팸으로 판별된 파일만 출력",
    )
    return parser.parse_args()


def run():
    args = parse_args()
    scan_path = args.scan_path.resolve()
    if not scan_path.is_dir():
        print(f"오류: 디렉터리가 아닙니다: {scan_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config(args.config.resolve())
    keywords = get_keywords(config)
    if not keywords:
        print("경고: 블랙리스트 키워드가 없습니다. 설정 파일을 확인하세요.", file=sys.stderr)

    quarantine_dir = args.quarantine_dir
    if quarantine_dir is None:
        quarantine_dir = get_quarantine_dir(config)
    else:
        quarantine_dir = quarantine_dir.resolve()

    ocr_lang = get_ocr_lang(config)
    files = collect_files(scan_path, SUPPORTED_EXTENSIONS)
    moved = []
    skipped_errors = []

    for file_path in files:
        try:
            text = extract_text(file_path, lang=ocr_lang)
        except Exception as e:
            skipped_errors.append((file_path, str(e)))
            continue

        if not is_spam(text, keywords):
            continue

        if args.dry_run:
            print(file_path)
            moved.append(file_path)
            continue

        try:
            if args.use_trash:
                move_to_trash(file_path)
            else:
                move_to_quarantine(file_path, quarantine_dir)
            moved.append(file_path)
        except Exception as e:
            skipped_errors.append((file_path, str(e)))

    if skipped_errors:
        for path, err in skipped_errors:
            print(f"스킵: {path} - {err}", file=sys.stderr)
    print(f"처리 완료: 스캔 {len(files)}개, 스팸 이동 {len(moved)}개")


if __name__ == "__main__":
    run()

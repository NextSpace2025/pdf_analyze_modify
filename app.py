"""Application entrypoint."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from src.ocr import _ensure_lang_data, check_tesseract, has_lang_data
from src.ui.app_window import App


def main() -> None:
    tess_err = check_tesseract()
    if tess_err:
        # OCR is optional for PDFs that contain embedded text.
        # Only block startup if Tesseract itself is missing.
        if "Tesseract OCR 엔진을 찾을 수 없습니다" in tess_err or "Tesseract OCR 엔진이 설치되어 있지" in tess_err:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Tesseract OCR required", tess_err)
            root.destroy()
            return
        if not has_lang_data("kor"):
            root = tk.Tk()
            root.withdraw()
            ok = messagebox.askyesno(
                "한국어 OCR 설치",
                "한국어 OCR 언어 데이터(kor)가 없습니다.\n\n"
                "지금 다운로드해서 앱에 설정할까요?\n"
                "(config/tessdata/kor.traineddata)\n\n"
                "Yes: 자동 설치\n"
                "No: 설치 없이 계속",
            )
            if ok:
                installed, msg = _ensure_lang_data("kor")
                if not installed:
                    messagebox.showwarning("설치 실패", msg)
            root.destroy()
    App().run()


if __name__ == "__main__":
    main()


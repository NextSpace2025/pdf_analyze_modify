"""로컬 GUI: 폴더 경로 입력, PDF 내용 분석, 폴더 내 파일 삭제(휴지통)."""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from threading import Thread

from src.ocr import check_tesseract, extract_text
from src.naming_api import DEFAULT_RULES, resolve_conflicts, suggest_name

PREVIEW_LENGTH = 500
# 네트워크(127.0.0.1, UNC 등) 경로에서 읽을 때 대기 시간(초). 초과 시 '읽기 시간 초과'로 표시
FILE_READ_TIMEOUT = 180


def _normalize_unc(path_str: str) -> str:
    """Windows에서 UNC(네트워크) 경로 정규화: //server/share -> \\server\\share."""
    s = path_str.strip()
    if sys.platform == "win32":
        s = s.replace("/", "\\")
    return s


def _safe_path(user_path: str) -> Path | None:
    if not user_path or not user_path.strip():
        return None
    raw = _normalize_unc(user_path)
    try:
        p = Path(raw)
        if sys.platform == "win32" and raw.startswith("\\\\"):
            pass
        else:
            p = p.resolve()
        return p if p.exists() else None
    except (OSError, RuntimeError):
        return None


def _analyze_one_file(f: Path, timeout_sec: int) -> dict:
    """한 PDF 분석. 타임아웃 시 읽기 시간 초과 사유 반환."""
    out: list = [None]
    err: list = [None]

    def run():
        try:
            out[0] = extract_text(f, lang="kor+eng")
        except Exception as e:
            err[0] = e

    th = Thread(target=run, daemon=True)
    th.start()
    th.join(timeout=timeout_sec)
    if th.is_alive():
        return {
            "name": f.name, "path": f, "preview": "",
            "ok": False,
            "reason": f"읽기 시간 초과 ({timeout_sec}초). 네트워크 경로(127.0.0.1, UNC 등)는 지연될 수 있습니다. 로컬로 복사하거나 다시 시도하세요.",
        }
    if err[0]:
        e = err[0]
        reason = str(e).strip() or type(e).__name__
        if len(reason) > 200:
            reason = reason[:200] + "…"
        return {"name": f.name, "path": f, "preview": "", "ok": False, "reason": f"분석 실패: {reason}"}
    text = out[0] or ""
    preview = (text[:PREVIEW_LENGTH] + "…") if len(text) > PREVIEW_LENGTH else text
    if text.strip():
        return {"name": f.name, "path": f, "preview": preview, "ok": True, "reason": "정상 추출 (내장 텍스트 또는 OCR)"}
    return {
        "name": f.name, "path": f, "preview": "",
        "ok": False,
        "reason": "텍스트를 추출할 수 없음. (내장 텍스트 없음, OCR 결과 없음 또는 이미지 품질 부족)",
    }


def _analyze_folder(folder: Path, timeout_sec: int = FILE_READ_TIMEOUT) -> list[dict]:
    pdf_ext = {".pdf"}
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in pdf_ext]
    return [_analyze_one_file(f, timeout_sec) for f in sorted(files)]


def _delete_to_trash(file_path: Path) -> bool:
    try:
        import send2trash
        send2trash.send2trash(str(file_path))
        return True
    except Exception:
        return False


def _rename_file(file_path: Path, new_name: str) -> tuple[bool, str]:
    """파일명 변경. 성공 시 (True, ''), 실패 시 (False, 오류 메시지)."""
    new_name = new_name.strip()
    if not new_name:
        return False, "파일명을 입력하세요."
    if "\\" in new_name or "/" in new_name or (sys.platform == "win32" and ":" in new_name):
        return False, "경로가 아닌 파일명만 입력하세요."
    if not new_name.lower().endswith(".pdf"):
        new_name = new_name + ".pdf"
    new_path = file_path.parent / new_name
    if new_path == file_path:
        return False, "동일한 이름입니다."
    if new_path.exists():
        return False, "같은 이름의 파일이 이미 있습니다."
    try:
        file_path.rename(new_path)
        return True, ""
    except OSError as e:
        return False, str(e)


def _ask_new_filename(parent: tk.Tk, current_name: str) -> str | None:
    """새 파일명 입력 대화상자. 확인 시 새 이름, 취소 시 None."""
    result: list[str | None] = [None]

    top = tk.Toplevel(parent)
    top.title("파일명 바꾸기")
    top.transient(parent)
    top.grab_set()
    ttk.Label(top, text="새 파일명:").pack(anchor=tk.W, padx=8, pady=(8, 0))
    entry = ttk.Entry(top, width=50)
    entry.pack(fill=tk.X, padx=8, pady=4)
    entry.insert(0, current_name)
    entry.select_range(0, tk.END)
    entry.focus_set()

    def on_ok():
        result[0] = entry.get().strip()
        top.destroy()

    def on_cancel():
        top.destroy()

    btn_frame = ttk.Frame(top)
    btn_frame.pack(pady=(0, 8))
    ttk.Button(btn_frame, text="확인", command=on_ok).pack(side=tk.LEFT, padx=2)
    ttk.Button(btn_frame, text="취소", command=on_cancel).pack(side=tk.LEFT, padx=2)
    top.bind("<Return>", lambda e: on_ok())
    top.bind("<Escape>", lambda e: on_cancel())
    top.wait_window()
    return result[0]


def _parse_rules_text(text: str) -> list[tuple[str, str]]:
    """한 줄에 '키워드,접두사' 형식으로 파싱. 빈 줄·형식 오류 줄 무시."""
    rules: list[tuple[str, str]] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if "," in line:
            key, _, prefix = line.partition(",")
            key, prefix = key.strip(), prefix.strip()
            if key:
                rules.append((key, prefix or ""))
    return rules


def _ask_naming_rules(parent: tk.Tk, initial_rules: list[tuple[str, str]]) -> list[tuple[str, str]] | None:
    """규칙 편집 다이얼로그. 확인 시 파싱된 규칙 목록, 취소 시 None."""
    result: list[tuple[str, str]] | None = None
    initial_text = "\n".join(f"{k},{v}" for k, v in initial_rules)
    top = tk.Toplevel(parent)
    top.title("사유 기반 이름 규칙")
    top.transient(parent)
    top.grab_set()
    ttk.Label(top, text="사유에 포함된 문구 → 접두사 (한 줄에 '키워드,접두사')").pack(
        anchor=tk.W, padx=8, pady=(8, 0)
    )
    text = scrolledtext.ScrolledText(top, width=50, height=10, font=("Consolas", 9))
    text.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
    text.insert(tk.END, initial_text)
    btn_frame = ttk.Frame(top)
    btn_frame.pack(pady=(0, 8))
    def on_ok():
        nonlocal result
        result = _parse_rules_text(text.get("1.0", tk.END))
        if not result:
            result = initial_rules
        top.destroy()
    def on_cancel():
        top.destroy()
    ttk.Button(btn_frame, text="적용", command=on_ok).pack(side=tk.LEFT, padx=2)
    ttk.Button(btn_frame, text="취소", command=on_cancel).pack(side=tk.LEFT, padx=2)
    top.bind("<Return>", lambda e: on_ok())
    top.bind("<Escape>", lambda e: on_cancel())
    top.wait_window()
    return result


TOOL_DESCRIPTION = (
    "PDF가 들어 있는 폴더 경로를 입력한 뒤 [분석]을 누르면, "
    "폴더 안의 PDF 텍스트를 추출·분석합니다. "
    "각 파일마다 파일명 변경·휴지통 삭제가 가능합니다."
)
FOOTER_TEXT = "axis_lab - 김재용 제작  |  문의 = 010-8423-1222"
DESC_WRAP_LENGTH = 650


def _create_readonly_scrolled_text(parent: tk.Misc, content: str, height: int, mousewheel_cb) -> scrolledtext.ScrolledText:
    """읽기 전용 ScrolledText 위젯 생성 (미리보기/사유용)."""
    w = scrolledtext.ScrolledText(parent, height=height, wrap=tk.WORD, font=("Consolas", 9))
    w.insert(tk.END, content or "(내용 없음)")
    w.config(state=tk.DISABLED)
    w.bind("<MouseWheel>", mousewheel_cb)
    return w


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PDF 분석 · 삭제")
        self.root.minsize(500, 400)
        self.root.geometry("700x550")
        self._result_frames: list[tk.Frame] = []
        self._current_results: list[dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        self._build_search_section()
        self._build_description_and_footer()
        self._build_message_row()
        self._build_result_list()

    def _build_search_section(self) -> None:
        search_frame = ttk.LabelFrame(self.root, text=" PDF 폴더 경로 ", padding=12)
        search_frame.pack(fill=tk.X, padx=16, pady=(16, 4))
        path_row = ttk.Frame(search_frame)
        path_row.pack(fill=tk.X)
        self.path_var = tk.StringVar()
        self.path_entry = ttk.Entry(path_row, textvariable=self.path_var, width=55)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(path_row, text="찾아보기", command=self._browse).pack(side=tk.LEFT, padx=(0, 4))
        self.analyze_btn = ttk.Button(path_row, text="분석", command=self._start_analyze)
        self.analyze_btn.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(path_row, text="사유 기반 일괄 변경", command=self._open_batch_rename).pack(side=tk.LEFT)

    def _build_description_and_footer(self) -> None:
        """PDF 폴더 경로 바로 아래에 툴 설명 + axis_lab 문구 배치."""
        block = ttk.Frame(self.root, padding=(16, 8, 16, 12))
        block.pack(fill=tk.X)
        tk.Label(
            block,
            text=TOOL_DESCRIPTION,
            wraplength=DESC_WRAP_LENGTH,
            justify=tk.LEFT,
            fg="#555",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=tk.W)
        tk.Label(
            block,
            text=FOOTER_TEXT,
            fg="gray",
            font=("Segoe UI", 12),
        ).pack(anchor=tk.W, pady=(8, 0))

    def _build_message_row(self) -> None:
        self.msg_var = tk.StringVar()
        ttk.Label(self.root, textvariable=self.msg_var, foreground="gray").pack(
            anchor=tk.W, padx=24, pady=(0, 4)
        )

    def _build_result_list(self) -> None:
        list_frame = ttk.Frame(self.root, padding=8)
        list_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas = tk.Canvas(list_frame, yscrollcommand=scrollbar.set, highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.canvas.yview)
        self.list_container = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.list_container, anchor=tk.NW)
        self.list_container.bind("<Configure>", self._on_list_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)

    def _on_list_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _browse(self):
        path = filedialog.askdirectory(title="PDF 폴더 선택")
        if path:
            self.path_var.set(path)

    def _start_analyze(self):
        path_str = self.path_var.get().strip()
        folder = _safe_path(path_str)
        if folder is None:
            self.msg_var.set("유효한 폴더 경로를 입력하세요.")
            return
        if not folder.is_dir():
            self.msg_var.set("폴더 경로가 아닙니다.")
            return
        self.msg_var.set("분석 중…")
        self.analyze_btn.config(state=tk.DISABLED)
        for w in self.list_container.winfo_children():
            w.destroy()
        self._result_frames.clear()
        self.canvas.configure(scrollregion=(0, 0, 0, 0))

        def run():
            results = _analyze_folder(folder)
            self.root.after(0, lambda: self._on_analyze_done(folder, results))

        Thread(target=run, daemon=True).start()

    def _on_analyze_done(self, folder: Path, results: list[dict]):
        self.analyze_btn.config(state=tk.NORMAL)
        self._current_results = results
        self.msg_var.set(f"폴더: {folder} — PDF {len(results)}개")
        if not results:
            ttk.Label(self.list_container, text="PDF 파일이 없습니다.").pack(anchor=tk.W)
            return
        for r in results:
            self._add_result_row(r)

    def _add_result_row(self, r: dict) -> None:
        frame = ttk.LabelFrame(self.list_container, text=r["name"], padding=4)
        frame.pack(fill=tk.X, pady=4)
        self._result_frames.append(frame)
        top = ttk.Frame(frame)
        top.pack(fill=tk.X)
        content_frame = ttk.Frame(frame)
        content_frame.pack(fill=tk.BOTH, expand=True, pady=2)
        content_frame.columnconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=1)
        content_frame.rowconfigure(0, weight=1)
        # 왼쪽: 내용 미리보기
        left_frame = ttk.LabelFrame(content_frame, text="내용 미리보기", padding=2)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)
        preview = _create_readonly_scrolled_text(
            left_frame,
            r["preview"] or "(추출된 텍스트 없음)",
            4,
            self._on_mousewheel,
        )
        preview.grid(row=0, column=0, sticky="nsew")
        # 오른쪽: 분석 결과·사유
        right_frame = ttk.LabelFrame(content_frame, text="분석 결과·사유", padding=2)
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(2, 0))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(0, weight=1)
        reason_text = _create_readonly_scrolled_text(
            right_frame, r.get("reason", ""), 4, self._on_mousewheel
        )
        reason_text.grid(row=0, column=0, sticky="nsew")
        # 액션 버튼
        ttk.Button(top, text="파일명 바꾸기", command=lambda: self._do_rename(r, frame)).pack(
            side=tk.RIGHT, padx=(0, 4)
        )
        ttk.Button(top, text="삭제(휴지통)", command=lambda: self._do_delete(r, frame)).pack(side=tk.RIGHT)

    def _do_rename(self, r: dict, frame: ttk.LabelFrame) -> None:
        new_name = _ask_new_filename(self.root, r["name"])
        if not new_name:
            return
        ok, err = _rename_file(r["path"], new_name)
        if not ok:
            messagebox.showerror("파일명 바꾸기", err)
            return
        r["path"] = r["path"].parent / (
            new_name if new_name.lower().endswith(".pdf") else new_name + ".pdf"
        )
        r["name"] = r["path"].name
        frame.configure(text=r["name"])
        self.msg_var.set("파일명을 변경했습니다.")

    def _do_delete(self, r: dict, frame: ttk.LabelFrame) -> None:
        if not messagebox.askyesno("확인", f"'{r['name']}'을(를) 휴지통으로 보낼까요?"):
            return
        if _delete_to_trash(r["path"]):
            self.msg_var.set("휴지통으로 이동했습니다.")
            frame.destroy()
        else:
            messagebox.showerror("오류", "휴지통으로 보내지 못했습니다.")

    def _open_batch_rename(self) -> None:
        if not self._current_results:
            self.msg_var.set("먼저 폴더를 분석하세요.")
            messagebox.showinfo("안내", "폴더를 선택한 뒤 [분석]을 실행한 다음 사용하세요.")
            return
        if len(self._current_results) != len(self._result_frames):
            messagebox.showinfo("안내", "목록이 변경되었습니다. 다시 분석한 뒤 시도하세요.")
            return
        rules = _ask_naming_rules(self.root, DEFAULT_RULES)
        if rules is None:
            return
        suggested = [suggest_name(r.get("reason", ""), r["name"], rules) for r in self._current_results]
        final_names = resolve_conflicts(suggested)
        changed = 0
        for r, frame, new_name in zip(self._current_results, self._result_frames, final_names):
            if new_name == r["name"]:
                continue
            ok, err = _rename_file(r["path"], new_name)
            if ok:
                r["path"] = r["path"].parent / new_name
                r["name"] = new_name
                frame.configure(text=r["name"])
                changed += 1
            else:
                messagebox.showerror("일괄 이름 변경", f"'{r['name']}' → '{new_name}': {err}")
                break
        if changed > 0:
            self.msg_var.set(f"사유 기반 규칙으로 {changed}개 파일 이름 변경 완료.")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    tess_err = check_tesseract()
    if tess_err:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Tesseract OCR 필요", tess_err)
        root.destroy()
    App().run()

"""Main application window and event handlers."""

from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, scrolledtext, ttk

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:  # pragma: no cover
    Image = None
    ImageDraw = None
    ImageTk = None

try:
    import pystray
except ImportError:  # pragma: no cover
    pystray = None

from src.api_client import suggest_name_with_external_api
from src.naming_api import DEFAULT_RULES, resolve_conflicts, suggest_name
from src.state_store import (
    get_recent_rename_logs,
    init_db,
    load_api_settings,
    log_rename,
    rollback_last_rename,
    save_api_settings,
)
from src.ui.services import analyze_folder, delete_to_trash, rename_file, safe_path
from src.ui.styles import (
    DESC_WRAP_LENGTH,
    FILE_READ_TIMEOUT,
    FOOTER_TEXT,
    TOOL_DESCRIPTION,
    XP_BG,
    XP_STATUS_BG,
    XP_TEXT,
    apply_xp_style,
)
from src.ui.widgets import (
    ask_naming_rules,
    ask_new_filename,
    create_readonly_scrolled_text,
)

PREVIEW_MAX_WIDTH = 320
PREVIEW_MAX_HEIGHT = 220


class App:
    def __init__(self):
        init_db()
        self.root = tk.Tk()
        self.root.title("PDF File Manager")
        self.root.geometry("1160x760")
        self.root.minsize(920, 620)
        self.root.configure(bg=XP_BG)

        self.path_var = tk.StringVar()
        self.msg_var = tk.StringVar(value="Ready")

        self._result_frames: list[ttk.LabelFrame] = []
        self._current_results: list[dict] = []
        self._is_analyzing = False
        self._current_page = "scan"
        self._page_before_settings = "manage"
        self._page_before_api_test = "settings"
        self._preview_photo = None
        self._result_list_frame = None
        self._tray_icon = None
        self._watch_folder: Path | None = None
        self._watched_file_names: set[str] = set()
        self._window_withdrawn = False
        self._watcher_started = False

        self._load_settings()
        apply_xp_style(self.root)
        self._build_ui()
        self._setup_tray()

    def _load_settings(self) -> None:
        settings = load_api_settings()
        self.api_base_url_var = tk.StringVar(value=settings["api_base_url"])
        self.api_key_var = tk.StringVar(value=settings["api_key"])
        self.api_model_var = tk.StringVar(value=settings["api_model"])
        self.use_external_api_var = tk.BooleanVar(value=settings["use_external_api"])
        self.mcp_name_var = tk.StringVar(value=settings["mcp_server_name"] or "context7")
        self.mcp_url_var = tk.StringVar(value=settings["mcp_server_url"])

    def _current_settings(self) -> dict:
        return {
            "api_base_url": self.api_base_url_var.get().strip(),
            "api_key": self.api_key_var.get().strip(),
            "api_model": self.api_model_var.get().strip(),
            "use_external_api": self.use_external_api_var.get(),
            "mcp_server_name": self.mcp_name_var.get().strip() or "context7",
            "mcp_server_url": self.mcp_url_var.get().strip(),
        }

    def _build_ui(self) -> None:
        root_pad = ttk.Frame(self.root, padding=10)
        root_pad.pack(fill=tk.BOTH, expand=True)

        self._build_header(root_pad)

        self.page_container = ttk.Frame(root_pad)
        self.page_container.pack(fill=tk.BOTH, expand=True)
        self.page_container.columnconfigure(0, weight=1)
        self.page_container.rowconfigure(0, weight=1)

        self.pages: dict[str, ttk.Frame] = {
            "scan": ScanPage(self.page_container, self),
            "manage": ManagePage(self.page_container, self),
            "settings": SettingsPage(self.page_container, self),
            "api_test": ApiTestPage(self.page_container, self),
        }
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

        self.show_page("scan")

    def _build_header(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(bar, text="PDF File Manager", font=("Tahoma", 10, "bold")).pack(side=tk.LEFT)

        self.settings_btn = ttk.Button(bar, text="⚙", width=3, command=lambda: self.show_page("settings"))
        self.settings_btn.pack(side=tk.RIGHT)

    def show_page(self, page_name: str) -> None:
        if page_name not in self.pages:
            return
        if page_name == "settings":
            self._page_before_settings = self._current_page
        if page_name == "api_test":
            self._page_before_api_test = self._current_page
        self._current_page = page_name
        self.pages[page_name].tkraise()

    def _build_api_settings_section(self, parent: ttk.Frame) -> None:
        section = ttk.LabelFrame(parent, text="AI API Settings")
        section.pack(fill=tk.X, pady=(0, 8))

        head = ttk.Frame(section, padding=(10, 8, 10, 4))
        head.pack(fill=tk.X)
        ttk.Label(head, text="⚙").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(head, text="Configure API Base URL / Model / Key used for Batch Rename").pack(side=tk.LEFT)
        ttk.Button(head, text="Save Settings", command=self._save_settings).pack(side=tk.RIGHT)

        row1 = ttk.Frame(section, padding=(10, 2, 10, 6))
        row1.pack(fill=tk.X)
        ttk.Checkbutton(row1, text="Use External API", variable=self.use_external_api_var).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(row1, text="Model").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.api_model_var, width=24).pack(side=tk.LEFT, padx=(6, 20))
        ttk.Label(row1, text="MCP Name").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.mcp_name_var, width=18, state="readonly").pack(side=tk.LEFT, padx=(6, 16))
        ttk.Button(row1, text="Attach context7", command=self._attach_context7).pack(side=tk.LEFT)

        row2 = ttk.Frame(section, padding=(10, 0, 10, 10))
        row2.pack(fill=tk.X)
        ttk.Label(row2, text="API Base URL", width=14).pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.api_base_url_var).pack(side=tk.LEFT, padx=(6, 16), fill=tk.X, expand=True)
        ttk.Label(row2, text="API Key").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.api_key_var, width=28, show="*").pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(row2, text="MCP URL").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.mcp_url_var, width=24).pack(side=tk.LEFT, padx=(6, 0))

    def _build_description(self, parent: ttk.Frame) -> None:
        block = ttk.Frame(parent, padding=(4, 0, 4, 8))
        block.pack(fill=tk.X)
        tk.Label(
            block,
            text=TOOL_DESCRIPTION,
            wraplength=DESC_WRAP_LENGTH,
            justify=tk.LEFT,
            fg=XP_TEXT,
            bg=XP_BG,
            font=("Tahoma", 9),
        ).pack(anchor=tk.W)
        tk.Label(
            block,
            text=FOOTER_TEXT,
            fg=XP_TEXT,
            bg=XP_BG,
            font=("Tahoma", 9),
        ).pack(anchor=tk.W, pady=(4, 0))

    def _build_message_row(self, parent: ttk.Frame) -> None:
        tk.Label(
            parent,
            textvariable=self.msg_var,
            fg=XP_TEXT,
            bg=XP_STATUS_BG,
            font=("Tahoma", 9),
            relief=tk.SUNKEN,
            bd=1,
            anchor="w",
            padx=6,
        ).pack(fill=tk.X, padx=4, pady=(0, 8))

    def _build_result_list(self, parent: ttk.Frame) -> None:
        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self._result_list_frame = list_frame

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas = tk.Canvas(
            list_frame,
            yscrollcommand=scrollbar.set,
            highlightthickness=0,
            bg=XP_BG,
            bd=0,
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.canvas.yview)

        self.list_container = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.list_container, anchor=tk.NW)

        self.list_container.bind("<Configure>", self._on_list_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        # Use a global mousewheel handler so scrolling works even when the pointer
        # is over child widgets inside the canvas (frames/labels/buttons).
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        if not getattr(self, "_mousewheel_bound", False):
            self.root.bind_all("<MouseWheel>", self._on_global_mousewheel, add="+")
            self._mousewheel_bound = True

    def _on_list_configure(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _is_descendant(self, widget: tk.Misc | None, ancestor: tk.Misc | None) -> bool:
        if widget is None or ancestor is None:
            return False
        w = widget
        while w is not None:
            if w == ancestor:
                return True
            w = getattr(w, "master", None)
        return False

    def _on_global_mousewheel(self, event):
        # Only affect the result list scrolling on the manage page.
        if self._current_page != "manage":
            return
        if self._result_list_frame is None or not hasattr(self, "canvas"):
            return

        under = self.root.winfo_containing(event.x_root, event.y_root)
        if self._is_descendant(under, self.canvas) or self._is_descendant(under, self._result_list_frame):
            return self._on_mousewheel(event)

    def _browse(self):
        path = filedialog.askdirectory(title="Select PDF folder")
        if path:
            self.path_var.set(path)
            if self._current_page == "scan":
                self.show_page("manage")
            self._start_analyze()

    def _start_analyze(self):
        if self._is_analyzing:
            self.msg_var.set("Analysis already running. Please wait.")
            return

        folder = safe_path(self.path_var.get().strip())
        if folder is None:
            self.msg_var.set("Enter a valid folder path.")
            return
        if not folder.is_dir():
            self.msg_var.set("The path is not a folder.")
            return

        self._is_analyzing = True
        self.msg_var.set("Analyzing...")
        self.analyze_btn.config(state=tk.DISABLED)

        def run():
            results = analyze_folder(folder, FILE_READ_TIMEOUT)
            self.root.after(0, lambda: self._on_analyze_done(folder, results))

        Thread(target=run, daemon=True).start()

    def _on_analyze_done(self, folder: Path, results: list[dict]):
        self._is_analyzing = False
        self.analyze_btn.config(state=tk.NORMAL)
        for widget in self.list_container.winfo_children():
            widget.destroy()
        self._result_frames.clear()
        self.canvas.configure(scrollregion=(0, 0, 0, 0))

        self._current_results = results
        self.msg_var.set(f"Folder: {folder} | PDF files: {len(results)}")

        if not results:
            ttk.Label(self.list_container, text="No PDF files found.").pack(anchor=tk.W, padx=8, pady=8)
            return

        for result in results:
            self._add_result_row(result)

        logs = get_recent_rename_logs(folder, limit=3)
        if logs:
            latest = logs[0]
            self.msg_var.set(
                f"Folder: {folder} | PDF files: {len(results)} | Last rename: {latest['before_name']} -> {latest['after_name']}"
            )

        self._watch_folder = folder
        try:
            self._watched_file_names = {f.name for f in folder.iterdir() if f.is_file()}
        except OSError:
            self._watched_file_names = {r["name"] for r in results}
        self._start_watcher()

    def _start_watcher(self) -> None:
        if self._watcher_started:
            return
        self._watcher_started = True
        Thread(target=self._watcher_loop, daemon=True).start()

    def _watcher_loop(self) -> None:
        """20분 간격으로 감시 폴더에 새 파일이 생겼는지 확인 (백그라운드일 때만)."""
        interval_sec = 20 * 60
        while True:
            time.sleep(interval_sec)
            if getattr(self, "_watch_folder", None) is None:
                continue
            if not getattr(self, "_window_withdrawn", False):
                continue
            self._check_new_files_background()

    def _check_new_files_background(self) -> None:
        """워커 스레드에서 호출. 새 파일 발견 시 메인 스레드로 알림 예약."""
        folder = self._watch_folder
        if folder is None or not folder.is_dir():
            return
        try:
            current = {f.name for f in folder.iterdir() if f.is_file()}
        except OSError:
            return
        new_ones = current - self._watched_file_names
        if not new_ones:
            return
        self.root.after(0, lambda: self._notify_new_files(new_ones))

    def _notify_new_files(self, new_set: set[str]) -> None:
        """메인 스레드. 새 파일 목록을 반영하고 Windows 토스트 알림."""
        self._watched_file_names |= new_set
        n = len(new_set)
        names_preview = ", ".join(sorted(new_set)[:5])
        if n > 5:
            names_preview += f" 외 {n - 5}개"
        title = "PDF File Manager"
        msg = f"새 파일 {n}개 추가됨: {names_preview}"
        if sys.platform == "win32":
            try:
                from win10toast import ToastNotifier
                toaster = ToastNotifier()
                toaster.show_toast(title, msg, duration=10, threaded=False)
            except Exception:
                pass

    def _add_result_row(self, result: dict) -> None:
        frame = ttk.LabelFrame(self.list_container, text=result["name"], padding=6)
        frame.pack(fill=tk.X, pady=5, padx=6)
        self._result_frames.append(frame)

        top = ttk.Frame(frame)
        top.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(top, text="View PDF", command=lambda: self._request_pdf_preview(result["path"])).pack(
            side=tk.RIGHT, padx=(0, 6)
        )
        ttk.Button(top, text="Rename", command=lambda: self._do_rename(result, frame)).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(top, text="Delete to Trash", command=lambda: self._do_delete(result, frame)).pack(side=tk.RIGHT)

        content = ttk.Frame(frame)
        content.pack(fill=tk.BOTH, expand=True)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(content, text="Text Preview", padding=4)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        preview = create_readonly_scrolled_text(
            left,
            result["preview"] or "(no text)",
            5,
            self._on_mousewheel,
        )
        preview.grid(row=0, column=0, sticky="nsew")

        right = ttk.LabelFrame(content, text="Analysis Result", padding=4)
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        reason = create_readonly_scrolled_text(
            right,
            result.get("reason", ""),
            5,
            self._on_mousewheel,
        )
        reason.grid(row=0, column=0, sticky="nsew")

    def _do_rename(self, result: dict, frame: ttk.LabelFrame) -> None:
        new_name = ask_new_filename(self.root, result["name"])
        if not new_name:
            return

        before_name = result["name"]
        ok, error_msg = rename_file(result["path"], new_name)
        if not ok:
            messagebox.showerror("Rename failed", error_msg)
            return

        final_name = new_name if new_name.lower().endswith(".pdf") else f"{new_name}.pdf"
        result["path"] = result["path"].parent / final_name
        result["name"] = final_name
        frame.configure(text=final_name)
        log_rename(result["path"].parent, before_name, final_name)
        self.msg_var.set(f"Renamed: {before_name} -> {final_name}")

    def _do_delete(self, result: dict, frame: ttk.LabelFrame) -> None:
        if not messagebox.askyesno("Confirm", f"Move '{result['name']}' to Trash?"):
            return
        if not delete_to_trash(result["path"]):
            messagebox.showerror("Error", "Failed to move to Trash.")
            return

        self.msg_var.set(f"Moved to Trash: {result['name']}")
        if frame in self._result_frames:
            idx = self._result_frames.index(frame)
            self._result_frames.pop(idx)
            if idx < len(self._current_results):
                self._current_results.pop(idx)
        frame.destroy()

    def _attach_context7(self) -> None:
        self.mcp_name_var.set("context7")
        self.msg_var.set("MCP set to context7.")

    def _save_settings(self) -> None:
        if self.use_external_api_var.get() and not self.api_base_url_var.get().strip():
            messagebox.showerror("Validation", "API Base URL is required when Use External API is enabled.")
            return
        if self.use_external_api_var.get():
            base = self.api_base_url_var.get().strip()
            if not (base.startswith("http://") or base.startswith("https://")):
                messagebox.showerror("Validation", "API Base URL must start with http:// or https://")
                return
        self.mcp_name_var.set("context7")
        save_api_settings(self._current_settings())
        self.msg_var.set("AI API settings saved.")

    def _open_batch_rename(self) -> None:
        if not self._current_results:
            self.msg_var.set("Analyze a folder first.")
            messagebox.showinfo("Info", "Run Analyze first.")
            return
        if len(self._current_results) != len(self._result_frames):
            messagebox.showinfo("Info", "Result list changed. Re-run Analyze.")
            return

        rules = ask_naming_rules(self.root, DEFAULT_RULES)
        if rules is None:
            return

        settings = self._current_settings()
        suggested: list[str] = []
        api_errors = 0

        for result in self._current_results:
            current_name = result["name"]
            reason = result.get("reason", "")
            new_name = None

            if settings["use_external_api"]:
                api_name, _api_error = suggest_name_with_external_api(
                    api_base_url=settings["api_base_url"],
                    api_key=settings["api_key"],
                    api_model=settings["api_model"],
                    reason=reason,
                    current_name=current_name,
                    mcp_server_name=settings["mcp_server_name"],
                    mcp_server_url=settings["mcp_server_url"],
                )
                if api_name:
                    new_name = api_name
                else:
                    api_errors += 1

            if not new_name:
                new_name = suggest_name(reason, current_name, rules)

            if not new_name.lower().endswith(".pdf"):
                new_name = f"{new_name}.pdf"
            suggested.append(new_name)

        final_names = resolve_conflicts(suggested)
        changed = 0

        for result, frame, new_name in zip(self._current_results, self._result_frames, final_names):
            if new_name == result["name"]:
                continue

            before_name = result["name"]
            ok, error_msg = rename_file(result["path"], new_name)
            if not ok:
                messagebox.showerror("Batch rename failed", f"{before_name} -> {new_name}: {error_msg}")
                break

            result["path"] = result["path"].parent / new_name
            result["name"] = new_name
            frame.configure(text=new_name)
            log_rename(result["path"].parent, before_name, new_name)
            changed += 1

        if changed == 0:
            self.msg_var.set("No files renamed.")
            return

        if api_errors > 0:
            self.msg_var.set(
                f"Renamed {changed} files. External API failed {api_errors} times; local rules were used."
            )
        else:
            self.msg_var.set(f"Renamed {changed} files.")

    def _rollback_last(self) -> None:
        folder = safe_path(self.path_var.get().strip())
        if folder is None or not folder.is_dir():
            self.msg_var.set("Set a valid folder path first.")
            return

        ok, message = rollback_last_rename(folder)
        self.msg_var.set(message)
        if ok:
            self._start_analyze()
        else:
            messagebox.showinfo("Rollback", message)

    def _setup_tray(self) -> None:
        """Windows 백그라운드: 트레이 아이콘 등록, 창 닫기 시 트레이로 숨김."""
        if pystray is None or Image is None or ImageDraw is None:
            return
        try:
            size = 32
            img = Image.new("RGB", (size, size), color=(236, 233, 216))
            d = ImageDraw.Draw(img)
            margin = 4
            d.rectangle([margin, margin, size - margin, size - margin], outline=(0, 0, 0), width=2)
            d.polygon([(size - margin - 8, margin), (size - margin, margin), (size - margin, margin + 8)], fill=(200, 200, 200))
            icon_image = img

            def show_window(_icon: object, _item: object) -> None:
                self.root.after(0, self._show_from_tray)

            def quit_app(_icon: object, _item: object) -> None:
                self.root.after(0, self._quit_from_tray)

            menu = pystray.Menu(
                pystray.MenuItem("창 열기", show_window, default=True),
                pystray.MenuItem("종료", quit_app),
            )
            self._tray_icon = pystray.Icon(
                "pdf_file_manager",
                icon_image,
                "PDF File Manager",
                menu,
            )
            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
            Thread(target=self._tray_icon.run, daemon=True).start()
        except Exception:
            pass

    def _on_close(self) -> None:
        """창 닫기 버튼: 트레이로 숨김 (백그라운드 유지)."""
        if self._tray_icon is not None:
            self._window_withdrawn = True
            self.root.withdraw()
        else:
            self.root.quit()

    def _show_from_tray(self) -> None:
        """트레이에서 창 다시 표시."""
        self._window_withdrawn = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _quit_from_tray(self) -> None:
        """트레이 메뉴 '종료': 앱 완전 종료."""
        self._stop_tray()
        self.root.quit()

    def _stop_tray(self) -> None:
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
            self._tray_icon = None

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self._stop_tray()

    def _request_pdf_preview(self, pdf_path: Path) -> None:
        manage = self.pages.get("manage")
        if manage is None or not hasattr(manage, "set_preview_loading"):
            return
        manage.set_preview_loading(pdf_path.name)

        def run():
            try:
                photo = self._render_pdf_first_page(pdf_path)
                self.root.after(0, lambda: manage.set_preview_image(photo, pdf_path.name))
            except Exception as exc:
                msg = str(exc).strip() or type(exc).__name__
                self.root.after(0, lambda: manage.set_preview_error(msg))

        Thread(target=run, daemon=True).start()

    def _render_pdf_first_page(self, pdf_path: Path):
        if fitz is None or Image is None or ImageTk is None:
            raise RuntimeError("PDF preview requires PyMuPDF and Pillow.")
        doc = fitz.open(pdf_path)
        try:
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        finally:
            doc.close()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.thumbnail((PREVIEW_MAX_WIDTH, PREVIEW_MAX_HEIGHT), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)


class ScanPage(ttk.Frame):
    def __init__(self, parent: ttk.Frame, app: App):
        super().__init__(parent)
        self.app = app

        section = ttk.LabelFrame(self, text="Scan Folder")
        section.pack(fill=tk.X, pady=(0, 10))

        row = ttk.Frame(section, padding=10)
        row.pack(fill=tk.X)
        self.path_entry = ttk.Entry(row, textvariable=self.app.path_var, width=70)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(row, text="Browse", command=self.app._browse).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row, text="Next", command=self._go_manage).pack(side=tk.LEFT)

        hint = ttk.Frame(self, padding=(4, 0, 4, 0))
        hint.pack(fill=tk.X)
        tk.Label(
            hint,
            text="Select a folder to scan. You'll manage rename/check operations on the next page.",
            justify=tk.LEFT,
            fg=XP_TEXT,
            bg=XP_BG,
            font=("Tahoma", 9),
        ).pack(anchor=tk.W)

        self.path_entry.bind("<Return>", lambda _e: self._go_manage())

    def _go_manage(self) -> None:
        self.app.show_page("manage")
        self.app._start_analyze()


class ManagePage(ttk.Frame):
    def __init__(self, parent: ttk.Frame, app: App):
        super().__init__(parent)
        self.app = app
        self._preview_photo = None
        self._preview_visible = True
        self._build_top_section()
        self.app._build_description(self)
        self.app._build_message_row(self)
        self._build_pdf_preview()
        self.app._build_result_list(self)

    def _build_pdf_preview(self) -> None:
        section = ttk.LabelFrame(self, text="PDF Preview")
        section.pack(fill=tk.X, pady=(0, 8))
        section.columnconfigure(0, weight=1)
        self.preview_section = section

        head = ttk.Frame(section, padding=(10, 6, 10, 2))
        head.pack(fill=tk.X)
        self.preview_title_var = tk.StringVar(value="(click 'View PDF' to load)")
        ttk.Label(head, textvariable=self.preview_title_var).pack(side=tk.LEFT)
        self.preview_toggle_btn = ttk.Button(head, text="Hide", width=8, command=self._toggle_preview)
        self.preview_toggle_btn.pack(side=tk.RIGHT)

        self.preview_body = ttk.Frame(section, padding=(10, 2, 10, 10))
        self.preview_body.pack(fill=tk.X)
        self.preview_label = ttk.Label(self.preview_body, anchor="center")
        self.preview_label.pack(fill=tk.X)

    def _toggle_preview(self) -> None:
        self._preview_visible = not self._preview_visible
        if self._preview_visible:
            self.preview_body.pack(fill=tk.X, padx=0, pady=0)
            self.preview_toggle_btn.configure(text="Hide")
        else:
            self.preview_body.pack_forget()
            self.preview_toggle_btn.configure(text="Show")

    def set_preview_loading(self, filename: str) -> None:
        if not self._preview_visible:
            self._toggle_preview()
        self.preview_title_var.set(f"Loading: {filename}")
        self.preview_label.configure(image="", text="Rendering preview...")
        self._preview_photo = None

    def set_preview_error(self, message: str) -> None:
        if not self._preview_visible:
            self._toggle_preview()
        self.preview_title_var.set("Preview failed")
        self.preview_label.configure(image="", text=message)
        self._preview_photo = None

    def set_preview_image(self, photo, filename: str) -> None:
        if not self._preview_visible:
            self._toggle_preview()
        self._preview_photo = photo
        self.preview_title_var.set(filename)
        self.preview_label.configure(image=self._preview_photo, text="")

    def _build_top_section(self) -> None:
        section = ttk.LabelFrame(self, text="PDF Manager")
        section.pack(fill=tk.X, pady=(0, 10))

        row = ttk.Frame(section, padding=10)
        row.pack(fill=tk.X)
        ttk.Label(row, text="Folder").pack(side=tk.LEFT, padx=(0, 6))
        self.path_entry = ttk.Entry(row, textvariable=self.app.path_var, width=62)
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        ttk.Button(row, text="Change", command=lambda: self.app.show_page("scan")).pack(side=tk.LEFT, padx=(0, 6))
        self.app.analyze_btn = ttk.Button(row, text="Analyze", command=self.app._start_analyze)
        self.app.analyze_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row, text="Batch Rename", command=self.app._open_batch_rename).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row, text="Rollback Last", command=self.app._rollback_last).pack(side=tk.LEFT)


class SettingsPage(ttk.Frame):
    def __init__(self, parent: ttk.Frame, app: App):
        super().__init__(parent)
        self.app = app

        head = ttk.Frame(self)
        head.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(head, text="Settings", font=("Tahoma", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(head, text="API Test", command=lambda: self.app.show_page("api_test")).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(head, text="Back", command=self._back).pack(side=tk.RIGHT)

        self.app._build_api_settings_section(self)

    def _back(self) -> None:
        target = self.app._page_before_settings or "manage"
        if target == "settings":
            target = "manage"
        self.app.show_page(target)


class ApiTestPage(ttk.Frame):
    def __init__(self, parent: ttk.Frame, app: App):
        super().__init__(parent)
        self.app = app
        self._is_running = False

        head = ttk.Frame(self)
        head.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(head, text="API Test", font=("Tahoma", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(head, text="Back", command=self._back).pack(side=tk.RIGHT)
        ttk.Button(head, text="Settings", command=lambda: self.app.show_page("settings")).pack(side=tk.RIGHT, padx=(0, 6))

        form = ttk.LabelFrame(self, text="Request")
        form.pack(fill=tk.X, pady=(0, 10))

        row1 = ttk.Frame(form, padding=10)
        row1.pack(fill=tk.X)
        ttk.Label(row1, text="API Base URL", width=14).pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.app.api_base_url_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 16))
        ttk.Label(row1, text="Model").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.app.api_model_var, width=18).pack(side=tk.LEFT, padx=(6, 0))

        row2 = ttk.Frame(form, padding=(10, 0, 10, 10))
        row2.pack(fill=tk.X)
        ttk.Checkbutton(row2, text="Use External API", variable=self.app.use_external_api_var).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Label(row2, text="API Key").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.app.api_key_var, width=28, show="*").pack(side=tk.LEFT, padx=(6, 16))
        ttk.Label(row2, text="MCP URL").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.app.mcp_url_var, width=24).pack(side=tk.LEFT, padx=(6, 0))

        row3 = ttk.Frame(form, padding=(10, 0, 10, 10))
        row3.pack(fill=tk.X)
        ttk.Label(row3, text="Current name", width=14).pack(side=tk.LEFT)
        self.current_name_var = tk.StringVar(value="sample.pdf")
        ttk.Entry(row3, textvariable=self.current_name_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 16))
        self.run_btn = ttk.Button(row3, text="Run Test", command=self._run_test)
        self.run_btn.pack(side=tk.LEFT)

        ttk.Label(form, text="Reason / Prompt").pack(anchor=tk.W, padx=10)
        self.reason_text = scrolledtext.ScrolledText(form, height=6, wrap=tk.WORD, font=("Tahoma", 9))
        self.reason_text.pack(fill=tk.X, padx=10, pady=(4, 10))
        self.reason_text.insert(
            tk.END,
            "Extracted text successfully. Please suggest a concise, safe filename.",
        )

        out = ttk.LabelFrame(self, text="Response")
        out.pack(fill=tk.BOTH, expand=True)
        self.output = scrolledtext.ScrolledText(out, height=10, wrap=tk.WORD, font=("Consolas", 9))
        self.output.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self._set_output("Ready.")

    def _back(self) -> None:
        target = self.app._page_before_api_test or "settings"
        if target == "api_test":
            target = "settings"
        self.app.show_page(target)

    def _set_output(self, text: str) -> None:
        self.output.config(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, text)
        self.output.config(state=tk.DISABLED)

    def _run_test(self) -> None:
        if self._is_running:
            return
        self._is_running = True
        self.run_btn.config(state=tk.DISABLED)
        self._set_output("Running...")

        settings = self.app._current_settings()
        reason = self.reason_text.get("1.0", tk.END).strip()
        current_name = (self.current_name_var.get() or "").strip() or "sample.pdf"

        if not settings["use_external_api"]:
            self._set_output("Use External API is disabled. Enable it to run this test.")
            self._is_running = False
            self.run_btn.config(state=tk.NORMAL)
            return
        if not (settings["api_base_url"].startswith("http://") or settings["api_base_url"].startswith("https://")):
            self._set_output("Invalid API Base URL. It must start with http:// or https://")
            self._is_running = False
            self.run_btn.config(state=tk.NORMAL)
            return

        def run():
            name, err = suggest_name_with_external_api(
                api_base_url=settings["api_base_url"],
                api_key=settings["api_key"],
                api_model=settings["api_model"],
                reason=reason,
                current_name=current_name,
                mcp_server_name=settings["mcp_server_name"],
                mcp_server_url=settings["mcp_server_url"],
                timeout_sec=12,
            )

            def done():
                self._is_running = False
                self.run_btn.config(state=tk.NORMAL)
                base = (settings["api_base_url"] or "").strip().rstrip("/")
                url = f"{base}/suggest-name" if base else "(empty base url)"
                key_state = "set" if (settings["api_key"] or "").strip() else "empty"
                if err:
                    self._set_output(f"POST {url}\napi_key: {key_state}\n\nERROR:\n{err}\n")
                    return
                self._set_output(f"POST {url}\napi_key: {key_state}\n\nsuggested_name:\n{name}\n")

            self.app.root.after(0, done)

        Thread(target=run, daemon=True).start()

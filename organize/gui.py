"""창. **여기는 그리기만 한다** — 무엇을 그릴지는 `gui_model.Session` 이 정한다.

`tkinter` 를 함수 안에서 늦게 import 한다. 없는 환경에서도 `organize` 의 나머지
기능은 그대로 돌아야 하기 때문이다(리눅스에서 tkinter 는 별도 패키지다).

버튼이 켜지고 꺼지는 규칙은 여기서 정하지 않는다. `Session.can_*` 를 그대로
따른다 — 규칙이 두 군데 있으면 어긋나고, 어긋나면 **미리보기를 안 본 채로
실행이 눌리는** 순간이 생긴다.
"""

from pathlib import Path

from organize.errors import OrganizeError
from organize.gui_model import Session


def run(repo_root: Path) -> int:
    """창을 띄운다. 창을 못 띄우면 한국어로 알리고 1 을 돌려준다."""
    try:
        import tkinter                                    # noqa: F401
    except Exception:
        raise OrganizeError(
            "이 파이썬에서는 창을 띄울 수 없습니다 (tkinter 없음).",
            hint="윈도우 파이썬에는 기본으로 들어 있습니다. "
                 "리눅스라면 'sudo apt install python3-tk' 로 설치하세요.\n"
                 "    창 없이 쓰려면: organize preview <레시피>")
    app = App(repo_root)
    app.window.mainloop()
    return 0


class App:
    """위젯 묶음. 상태는 전부 `Session` 이 들고 있다."""

    def __init__(self, repo_root: Path) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.session = Session(repo_root)

        self.window = tk.Tk()
        self.window.title("organize — 파일 정리")
        self.window.geometry("980x620")
        self.window.minsize(760, 480)

        self.root_var = tk.StringVar()
        self.recipe_var = tk.StringVar()
        self.dest_var = tk.StringVar()
        self.status_var = tk.StringVar(value="정리할 폴더를 고르고 미리보기를 눌러 주세요.")

        self._build()
        self._sync_buttons()

    # ── 화면 만들기 ──────────────────────────────────────────────
    def _build(self) -> None:
        tk, ttk = self.tk, self.ttk
        pad = {"padx": 10, "pady": 6}

        고르는곳 = ttk.LabelFrame(self.window, text="무엇을 어떻게")
        고르는곳.pack(fill="x", **pad)
        고르는곳.columnconfigure(1, weight=1)

        ttk.Label(고르는곳, text="정리할 폴더").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(고르는곳, textvariable=self.root_var).grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Button(고르는곳, text="찾아보기…", command=self._pick_root
                   ).grid(row=0, column=2, padx=8)

        ttk.Label(고르는곳, text="무엇을 할까").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.recipe_box = ttk.Combobox(고르는곳, textvariable=self.recipe_var,
                                       state="readonly",
                                       values=self.session.recipe_names())
        self.recipe_box.grid(row=1, column=1, sticky="ew", pady=6)
        self.recipe_box.bind("<<ComboboxSelected>>", lambda _e: self._on_recipe())

        ttk.Label(고르는곳, text="보낼 곳 (선택)").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(고르는곳, textvariable=self.dest_var, state="readonly"
                  ).grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Button(고르는곳, text="찾아보기…", command=self._pick_dest
                   ).grid(row=2, column=2, padx=8)

        누르는곳 = ttk.Frame(self.window)
        누르는곳.pack(fill="x", **pad)
        self.btn_preview = ttk.Button(누르는곳, text="미리보기", command=self._preview)
        self.btn_apply = ttk.Button(누르는곳, text="실행", command=self._apply)
        self.btn_undo = ttk.Button(누르는곳, text="되돌리기", command=self._undo)
        for b in (self.btn_preview, self.btn_apply, self.btn_undo):
            b.pack(side="left", padx=(0, 8))

        # 밖으로 나갈 때만 보이는 경고. 평소에는 자리도 차지하지 않는다.
        self.warn = tk.Label(self.window, anchor="w", justify="left",
                             fg="#8a4b00", bg="#fdf3e0", padx=10, pady=8)

        표 = ttk.Frame(self.window)
        표.pack(fill="both", expand=True, **pad)
        cols = ("kind", "name", "dest", "reason")
        self.tree = ttk.Treeview(표, columns=cols, show="headings", height=14)
        for c, 제목, w in (("kind", "종류", 90), ("name", "파일", 220),
                          ("dest", "어디로", 380), ("reason", "왜", 240)):
            self.tree.heading(c, text=제목)
            self.tree.column(c, width=w, anchor="w")
        # 밖으로 나가는 줄은 눈에 띄게 — 무게가 다른 일이다.
        self.tree.tag_configure("leaving", background="#fdf3e0", foreground="#8a4b00")
        sb = ttk.Scrollbar(표, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        ttk.Label(self.window, textvariable=self.status_var, anchor="w"
                  ).pack(fill="x", padx=10, pady=(0, 10))

    # ── 버튼이 하는 일 ───────────────────────────────────────────
    def _pick_root(self) -> None:
        from organize import picker
        with self._reporting("폴더 고르기"):
            chosen = picker.ask_folder("정리할 폴더를 고르세요",
                                       start=self.session.root)
            if chosen is None:
                return
            self.session.set_root(chosen)
            self.root_var.set(str(chosen))
            self._clear_table()
            self.status_var.set("미리보기를 눌러 무엇이 어디로 갈지 확인하세요.")

    def _pick_dest(self) -> None:
        """보낼 곳을 골라 이름표(`@백업`)로 등록한다.

        레시피가 `@백업` 을 쓰고 있을 때 그 위치를 창에서 바꿀 수 있게 한다.
        타이핑이 없으므로 오타로 엉뚱한 곳에 쏟을 일이 없다.
        """
        from organize import picker
        with self._reporting("보낼 곳 고르기"):
            chosen = picker.ask_folder("보낼 곳을 고르세요 (USB·SD카드 등)")
            if chosen is None:
                return
            picker.store_picked_path(self.session.repo_root, "백업", chosen)
            self.dest_var.set(str(chosen))
            self.session.set_recipe(self.session.recipe_name)   # 미리보기 무효화
            self._clear_table()
            self.status_var.set(
                f"@백업 → {chosen} 로 저장했습니다. 레시피의 dest 가 \"@백업\" 이면 이리로 갑니다.")

    def _on_recipe(self) -> None:
        with self._reporting("정리 방식 고르기"):
            self.session.set_recipe(self.recipe_var.get())
            self._clear_table()
            self.status_var.set("미리보기를 눌러 무엇이 어디로 갈지 확인하세요.")

    def _preview(self) -> None:
        with self._reporting("미리보기"):
            view = self.session.preview()
            self._fill_table(view)
            self.status_var.set(
                f"총계  {view.summary}      (미리보기입니다 — 파일은 그대로입니다)")

    def _apply(self) -> None:
        with self._reporting("실행"):
            done = self.session.apply()
            self._clear_table()
            줄 = f"완료. 옮김 {done.moved} · 폴더 생성 {done.folders} · 실패 {done.failed}"
            if done.log_path:
                줄 += "     되돌리기를 누르면 되돌릴 수 있습니다."
            self.status_var.set(줄)
            if done.messages:
                self._show("실행 결과", "\n".join(done.messages))

    def _undo(self) -> None:
        with self._reporting("되돌리기"):
            back = self.session.undo()
            self._clear_table()
            self.status_var.set(f"되돌림 {back.restored} · 실패 {back.failed}")
            if back.messages:
                self._show("되돌리기 결과", "\n".join(back.messages))

    # ── 표 그리기 ────────────────────────────────────────────────
    def _clear_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.warn.pack_forget()
        self._sync_buttons()

    def _fill_table(self, view) -> None:
        self.tree.delete(*self.tree.get_children())
        for r in view.rows:
            self.tree.insert("", "end",
                             values=(r.kind, r.name, r.dest, r.reason),
                             tags=("leaving",) if r.leaving else ())
        if view.warnings:
            self.warn.config(text="⚠  " + "\n⚠  ".join(view.warnings))
            self.warn.pack(fill="x", padx=10, pady=(0, 4), before=self.tree.master)
        else:
            self.warn.pack_forget()
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        """버튼 상태는 **Session 이 정한 대로만** 따른다.

        여기서 따로 판단하면 규칙이 두 군데가 되고, 어긋나는 순간 미리보기를
        안 본 채로 실행이 눌린다. 이 도구가 가장 경계하는 일이다.
        """
        def 켬(b, on):
            b.state(["!disabled"] if on else ["disabled"])
        켬(self.btn_preview, self.session.can_preview)
        켬(self.btn_apply, self.session.can_apply)
        켬(self.btn_undo, self.session.can_undo)

    # ── 오류를 창으로 ────────────────────────────────────────────
    def _show(self, title: str, body: str) -> None:
        from tkinter import messagebox
        messagebox.showinfo(title, body, parent=self.window)

    class _Reporting:
        def __init__(self, app, what): self.app, self.what = app, what

        def __enter__(self): return self

        def __exit__(self, exc_type, exc, tb):
            if exc is None:
                return False
            from tkinter import messagebox
            if isinstance(exc, OrganizeError):
                몸 = exc.message + (f"\n\n{exc.hint}" if exc.hint else "")
            else:
                # 파이썬 예외 원문을 그대로 보여주지 않는다(전역 규칙).
                몸 = (f"{self.what} 중 예상치 못한 오류가 났습니다.\n\n"
                      "디스크 상태나 쓰기 권한을 확인해 주세요.")
            messagebox.showerror(self.what, 몸, parent=self.app.window)
            self.app.status_var.set(f"{self.what} 실패 — 위 안내를 확인해 주세요.")
            self.app._sync_buttons()
            return True                    # 창이 죽지 않는다

    def _reporting(self, what: str):
        """무엇이 터지든 창은 살아 있고, 사람이 읽을 말로 알린다."""
        return self._Reporting(self, what)

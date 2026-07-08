"""devtrail Textual 대시보드.

실행:
    python dashboard.py
    또는 python start.py (시작 점검 포함)
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RichLog,
    Static,
)
from textual.widgets.option_list import Option

PROJECT = Path(__file__).parent.resolve()
PYTHON = sys.executable

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


# ── 명령어 맵 ─────────────────────────────────────────────────────────────────
#
# (phase_name, phase_desc, commands)
# commands: [(cmd, summary, arg_defs)]
# arg_defs: [(name, prompt, required, kind)]  kind: "str" | "bool" | "path"

PHASES: list[tuple[str, str, list]] = [
    (
        "캡처", "메모·세션 기록 — LLM 불필요",
        [
            ("capture",        "텍스트 메모 저장", [
                ("text",           "메모 내용",                       True,  "str"),
                ("--project",      "프로젝트명 (Enter=스킵)",          False, "str"),
            ]),
            ("capture-session", "작업 세션 요약 저장", [
                ("--project",      "프로젝트명 (Enter=스킵)",          False, "str"),
                ("--from-repo",    "git 로그 포함",                    False, "bool"),
                ("--from-agent",   "LLM 요약 포함",                    False, "bool"),
                ("--summary-file", "요약 파일 경로 (Enter=스킵)",      False, "path"),
            ]),
            ("daily-log",      "오늘 작업 로그 생성", [
                ("--project",      "프로젝트명 (Enter=스킵)",          False, "str"),
            ]),
            ("install-hooks",  "git 레포에 자동 캡처 hook 설치", [
                ("repo",           "레포지토리 경로",                  True,  "path"),
                ("--project",      "프로젝트명 (Enter=폴더명 사용)",   False, "str"),
                ("--force",        "기존 hook 덮어쓰기",               False, "bool"),
            ]),
        ],
    ),
    (
        "분석", "노트 분석 → 후보 생성 — LLM 필요",
        [
            ("distill-today",        "오늘 노트 → Knowledge/Blog/Memory 후보", []),
            ("nightly-distill",      "야간 전체 파이프라인",                   []),
            ("weekly-distill",       "주간 요약",                              []),
            ("suggest-knowledge",    "지식 후보만 생성",                       []),
            ("suggest-blog-topics",  "블로그 아이디어 후보",                   []),
            ("suggest-memory-patch", "AgentMemory 패치 후보",                  []),
            ("update-open-loops",    "미해결 이슈 목록 업데이트",              []),
            ("build-context",        "주제별 컨텍스트 번들 생성", [
                ("topic",            "주제",                           True, "str"),
            ]),
        ],
    ),
    (
        "관리", "후보 검토·승격·검색 — LLM 불필요",
        [
            ("list-candidates",    "후보 목록 보기",           []),
            ("preview-candidate",  "후보 내용 미리보기", [
                ("rel_path",       "60_Candidates/ 기준 경로", True, "str"),
            ]),
            ("promote-candidate",  "후보 → 공식 지식 승격", [
                ("rel_path",       "후보 경로 (vault 기준)",   True, "str"),
            ]),
            ("promote-all",        "후보 전체 일괄 승격", [
                ("--kind",         "종류 필터 (Enter=전체)",   False, "str"),
            ]),
            ("apply-memory-patch", "AgentMemory 패치 적용", [
                ("--interactive",  "대화형 모드",              False, "bool"),
            ]),
            ("search",             "Vault 키워드 검색", [
                ("query",          "검색어",                   True, "str"),
            ]),
            ("related",            "관련 노트 찾기", [
                ("rel_path",       "기준 노트 경로",           True, "str"),
            ]),
            ("index-vault",        "Vault 인덱스 갱신",        []),
        ],
    ),
    (
        "출력", "블로그·포트폴리오·이력서 — LLM 필요",
        [
            ("worklog",               "오늘 작업 정리",          []),
            ("todo",                  "다음 할 일 목록",         []),
            ("blog write",            "블로그 초안 작성", [
                ("topic",             "주제",                    True,  "str"),
                ("--project",         "프로젝트명 (Enter=스킵)", False, "str"),
            ]),
            ("blog revise",           "블로그 초안 다듬기", [
                ("path",              "초안 파일 경로",          True,  "path"),
            ]),
            ("blog list",             "블로그 초안 목록",        []),
            ("blog preview",          "최신 초안 미리보기", [
                ("target",            "파일명 (Enter=최신)",     False, "str"),
            ]),
            ("portfolio",             "포트폴리오 전체 초안",    []),
            ("resume",                "이력서 생성",             []),
            ("suggest-career-bullets","경력 불릿 추출", [
                ("--project",         "프로젝트명 (Enter=스킵)", False, "str"),
            ]),
            ("push-digest",           "Telegram 다이제스트 전송", [
                ("--daily",           "일간 포함",               False, "bool"),
                ("--weekly",          "주간 포함",               False, "bool"),
            ]),
        ],
    ),
    (
        "시스템", "Vault 초기화·봇·스케줄러·기타",
        [
            ("init-vault",     "Vault 폴더 구조 초기화",         []),
            ("print-schedule", "OS 스케줄러 명령 출력", [
                ("--windows",  "Windows 작업 스케줄러 형식",     False, "bool"),
                ("--cron",     "cron 형식",                      False, "bool"),
            ]),
            ("serve-bot",      "Telegram 봇 시작",               []),
            ("capture-commit", "git 커밋 수동 캡처 (훅 누락 시)", [
                ("--repo",     "저장소 경로 (Enter=현재)",        False, "str"),
                ("--project",  "프로젝트명 (Enter=스킵)",         False, "str"),
                ("--from-agent","LLM 요약 포함",                  False, "bool"),
            ]),
            ("ask",            "자연어로 명령 실행", [
                ("text",       "하고 싶은 것을 자연어로",         True,  "str"),
                ("-y",         "확인 없이 바로 실행",             False, "bool"),
            ]),
        ],
    ),
]


# ── Vault 상태 읽기 ───────────────────────────────────────────────────────────

def _vault_status(vault: Path) -> dict:
    today = time.strftime("%Y-%m-%d")

    raw = sum(
        1 for p in vault.rglob("*.md")
        if any(str(p.relative_to(vault)).startswith(pfx)
               for pfx in ("00_Inbox", "10_Worklog"))
    )

    cand_by_kind: dict[str, int] = {}
    cand_dir = vault / "60_Candidates"
    if cand_dir.exists():
        for p in cand_dir.rglob("*.md"):
            k = p.parent.name
            cand_by_kind[k] = cand_by_kind.get(k, 0) + 1

    knowledge = sum(1 for _ in (vault / "20_Knowledge").rglob("*.md")) \
        if (vault / "20_Knowledge").exists() else 0

    last_distill = ""
    digest_dir = vault / "50_Outputs" / "Digest"
    if digest_dir.exists():
        digests = sorted(digest_dir.glob("*.md"), reverse=True)
        if digests:
            m = re.match(r"(\d{4}-\d{2}-\d{2})", digests[0].stem)
            last_distill = m.group(1) if m else ""

    loops: list[str] = []
    loops_file = vault / "40_AgentMemory" / "05_OpenLoops.md"
    if loops_file.exists():
        content = loops_file.read_text(encoding="utf-8")
        items = re.findall(r"^[-*]\s+(?:\[[ x]\]\s+)?(.+)$", content, re.MULTILINE)
        loops = [i.strip() for i in items if i.strip()][:5]

    return {
        "today": today,
        "raw": raw,
        "knowledge": knowledge,
        "candidates": sum(cand_by_kind.values()),
        "cand_by_kind": cand_by_kind,
        "distill_today": last_distill == today,
        "last_distill": last_distill,
        "open_loops": loops,
    }


# ── 모달: 명령 선택 ───────────────────────────────────────────────────────────

class CommandModal(ModalScreen):
    BINDINGS = [("escape", "cancel", "취소")]

    def __init__(self, phase_idx: int) -> None:
        super().__init__()
        self.phase_name, self.phase_desc, self.commands = PHASES[phase_idx]

    def compose(self) -> ComposeResult:
        with Container(id="cmd-modal"):
            yield Label(
                f"[bold]{self.phase_name}[/bold]  [dim]{self.phase_desc}[/dim]",
                id="modal-title",
            )
            yield OptionList(
                *[Option(f"  {cmd:<26}  {summary}") for cmd, summary, _ in self.commands],
                id="cmd-list",
            )
            yield Label("[dim]↑↓ 이동   Enter 선택   Esc 취소[/dim]", id="modal-hint")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_index)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── 모달: 인자 입력 ───────────────────────────────────────────────────────────

class ArgModal(ModalScreen):
    BINDINGS = [("escape", "cancel", "취소")]

    def __init__(self, cmd: str, summary: str, arg_defs: list) -> None:
        super().__init__()
        self.cmd = cmd
        self.summary = summary
        self.arg_defs = arg_defs

    def compose(self) -> ComposeResult:
        with Container(id="arg-modal"):
            yield Label(
                f"[bold cyan]{self.cmd}[/bold cyan]  [dim]{self.summary}[/dim]",
                id="modal-title",
            )
            with Vertical(id="arg-form"):
                for name, prompt, required, kind in self.arg_defs:
                    req = "[bold yellow]✶[/bold yellow] " if required else "  "
                    yield Label(f"{req}[dim]{prompt}[/dim]", classes="arg-label")
                    widget_id = f"arg-{name.lstrip('-').replace('-', '_')}"
                    if kind == "bool":
                        yield Checkbox(name, id=widget_id)
                    else:
                        yield Input(
                            placeholder="(Enter=스킵)" if not required else "",
                            id=widget_id,
                        )
            with Horizontal(classes="btn-row"):
                yield Button("실행  ↵", variant="primary", id="run-btn")
                yield Button("취소  Esc", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        first = self.query("Input, Checkbox").first()
        if first:
            first.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "run-btn":
            self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self) -> None:
        args: list[str] = []
        for name, prompt, required, kind in self.arg_defs:
            widget_id = f"arg-{name.lstrip('-').replace('-', '_')}"
            is_flag = name.startswith("-")

            if kind == "bool":
                cb = self.query_one(f"#{widget_id}", Checkbox)
                if cb.value:
                    args.append(name)
            else:
                inp = self.query_one(f"#{widget_id}", Input)
                val = inp.value.strip()
                if not val and required:
                    inp.focus()
                    self.notify(f"'{prompt}' 는 필수 항목입니다.", severity="warning")
                    return
                if val:
                    args.extend([name, val] if is_flag else [val])

        self.dismiss(args)


# ── 메인 앱 ───────────────────────────────────────────────────────────────────

class DevtrailApp(App):

    CSS = """
    Screen {
        background: #0d1117;
        layers: base overlay;
    }

    Header {
        background: #161b22;
        color: #58a6ff;
    }

    Footer {
        background: #161b22;
        color: #6e7681;
    }

    #sidebar {
        width: 32;
        border-right: solid #21262d;
        padding: 0 1;
        overflow-y: auto;
        background: #0d1117;
    }

    #output {
        padding: 0 1;
        background: #0d1117;
    }

    /* ── 명령 선택 모달 ── */
    CommandModal {
        align: center top;
    }

    #cmd-modal {
        background: $surface;
        border: solid #58a6ff;
        padding: 1 2;
        width: 80%;
        max-height: 85%;
        margin-top: 3;
    }

    #cmd-list {
        border: none;
        background: $surface;
        height: auto;
        max-height: 28;
    }

    #arg-modal {
        background: $surface;
        border: solid #58a6ff;
        padding: 1 2;
        width: 58%;
        height: auto;
    }

    /* ── 인자 입력 모달 ── */
    ArgModal {
        align: center middle;
    }



    #arg-form {
        margin-top: 1;
    }

    .arg-label {
        color: #8b949e;
        margin-top: 1;
    }

    Input {
        border: tall #30363d;
        background: #0d1117;
        color: #e6edf3;
        margin-bottom: 0;
    }

    Input:focus {
        border: tall #58a6ff;
    }

    Checkbox {
        color: #e6edf3;
        margin-bottom: 0;
    }

    .btn-row {
        height: 3;
        margin-top: 1;
        align: right middle;
    }

    Button {
        margin-left: 1;
        min-width: 10;
    }

    Button#run-btn {
        background: #238636;
        color: #ffffff;
        border: tall #2ea043;
    }

    Button#cancel-btn {
        background: #21262d;
        color: #8b949e;
        border: tall #30363d;
    }

    /* ── 공통 모달 타이틀 ── */
    #modal-title {
        padding-bottom: 1;
        border-bottom: solid #21262d;
        margin-bottom: 1;
    }

    #modal-hint {
        margin-top: 1;
        color: #6e7681;
    }
    """

    BINDINGS = [
        Binding("1", "open_phase(0)", "캡처",    show=True),
        Binding("2", "open_phase(1)", "분석",    show=True),
        Binding("3", "open_phase(2)", "관리",    show=True),
        Binding("4", "open_phase(3)", "출력",    show=True),
        Binding("5", "open_phase(4)", "시스템",  show=True),
        Binding("r", "refresh",       "새로고침", show=True),
        Binding("ctrl+l", "clear_log","지우기",   show=False),
        Binding("q", "quit",          "종료",    show=True),
    ]

    def __init__(self, vault: Path) -> None:
        super().__init__()
        self.vault = vault

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("", id="vault-stats")
            yield RichLog(id="output", highlight=True, markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "DEVTRAIL"
        self.sub_title = "Personal AI Dashboard"
        self.action_refresh()
        self.set_interval(30, self.action_refresh)

    # ── 사이드바 갱신 ──────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._load_status()

    @work(thread=True)
    def _load_status(self) -> None:
        st = _vault_status(self.vault)
        self.call_from_thread(self._render_sidebar, st)

    def _render_sidebar(self, st: dict) -> None:
        distill_color = "green" if st["distill_today"] else "yellow"
        distill_text  = "오늘 ✓" if st["distill_today"] else (st["last_distill"] or "없음")

        lines = [
            "[bold #58a6ff]VAULT[/bold #58a6ff]",
            f"  [dim]raw[/dim]     [bold]{st['raw']}[/bold]",
            f"  [dim]지식[/dim]    [bold]{st['knowledge']}[/bold]",
            f"  [dim]distill[/dim] [{distill_color}]{distill_text}[/{distill_color}]",
        ]

        if st["cand_by_kind"]:
            lines += ["", "[bold #58a6ff]CANDIDATES[/bold #58a6ff]"]
            total = st["candidates"]
            lines.append(f"  [dim]전체[/dim]  [bold yellow]{total}[/bold yellow]")
            for k, v in sorted(st["cand_by_kind"].items()):
                short_k = k[:14] if len(k) > 14 else k
                lines.append(f"  [dim]{short_k:<14}[/dim] {v}")

        if st["open_loops"]:
            lines += ["", "[bold #58a6ff]OPEN LOOPS[/bold #58a6ff]"]
            for item in st["open_loops"]:
                short = item[:25] + "…" if len(item) > 26 else item
                lines.append(f"  [dim]·[/dim] {short}")

        lines += ["", f"  [dim]{st['today']}[/dim]"]
        self.query_one("#vault-stats", Static).update("\n".join(lines))

    # ── 명령 실행 흐름 ─────────────────────────────────────────────

    def action_open_phase(self, idx: int) -> None:
        self.push_screen(CommandModal(idx), self._make_cmd_callback(idx))

    def _make_cmd_callback(self, phase_idx: int):
        def callback(cmd_idx):
            if cmd_idx is None:
                return
            _, _, commands = PHASES[phase_idx]
            cmd, summary, arg_defs = commands[cmd_idx]
            if arg_defs:
                self.push_screen(
                    ArgModal(cmd, summary, arg_defs),
                    lambda args: self._execute(cmd, args),
                )
            else:
                self._execute(cmd, [])
        return callback

    def _execute(self, cmd: str, args: list[str] | None) -> None:
        if args is None:
            return
        log = self.query_one("#output", RichLog)
        ts = time.strftime("%H:%M:%S")
        log.write(
            f"\n[bold #58a6ff]▶ [{ts}] devtrail {cmd}[/bold #58a6ff]"
            + (f" [dim]{' '.join(args)}[/dim]" if args else "")
        )
        log.write("[dim]" + "─" * 56 + "[/dim]")
        self._run_subprocess(cmd, args)

    @work(thread=True)
    def _run_subprocess(self, cmd: str, args: list[str]) -> None:
        log = self.query_one("#output", RichLog)
        try:
            proc = subprocess.Popen(
                [PYTHON, "-m", "app.cli", *cmd.split(), *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(PROJECT),
            )
            for line in proc.stdout or []:
                self.call_from_thread(log.write, line.rstrip())
            proc.wait()
            color = "green" if proc.returncode == 0 else "red"
            label = "완료" if proc.returncode == 0 else f"오류 (exit {proc.returncode})"
        except Exception as e:
            color, label = "red", f"실행 실패: {e}"

        self.call_from_thread(log.write, f"[{color}]── {label} ──[/{color}]")
        self.call_from_thread(self._load_status)

    # ── 기타 액션 ──────────────────────────────────────────────────

    def action_clear_log(self) -> None:
        self.query_one("#output", RichLog).clear()

    def action_quit(self) -> None:
        self.exit()


# ── 진입점 ───────────────────────────────────────────────────────────────────

def run(vault: Path) -> None:
    DevtrailApp(vault).run()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv(PROJECT / ".env")
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH") or os.environ.get("OBSIDIAN_VAULT_DIR", "")
    if not vault_path or not Path(vault_path).exists():
        print("OBSIDIAN_VAULT_PATH가 .env에 설정되어 있지 않습니다.")
        sys.exit(1)

    run(Path(vault_path))

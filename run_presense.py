"""Windows desktop entry. --demo works without audio models or API keys."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent


def load_config():
    import yaml
    path = ROOT / "config.yaml"
    if not path.exists():
        raise RuntimeError("Run setup_presense.bat or copy config.yaml.example to config.yaml")
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    for section, env in (("openai", "OPENAI_API_KEY"), ("deepl", "DEEPL_API_KEY")):
        config.setdefault(section, {})
        if os.environ.get(env):
            config[section]["api_key"] = os.environ[env]
    return config


def main():
    parser = argparse.ArgumentParser(description="PreSense V0 desktop prototype")
    parser.add_argument("--demo", action="store_true", help="scripted fixture; no AI or audio")
    parser.add_argument("--local", action="store_true", help="local Ollama translation and prediction, no API key")
    parser.add_argument("--local-model", help="downloaded Ollama model; implies --local")
    parser.add_argument("--check-local", action="store_true", help="test Ollama translation without loading audio models")
    parser.add_argument("--headless", action="store_true", help="print protocol snapshots")
    parser.add_argument("--seconds", type=float, default=0, help="auto-stop after N seconds")
    parser.add_argument("--device", type=int, help="loopback device index from --list-devices")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    config = None
    if not args.demo or args.check_local:
        config = load_config()
        if args.local or args.local_model or args.check_local:
            config.setdefault("translation", {})["translation_model"] = "ollama"
        if args.local_model:
            config.setdefault("ollama", {})["model"] = args.local_model
    if args.check_local:
        from presense.local_model import LocalModel
        async def check_local():
            opts = config.get("ollama", {})
            model = LocalModel(model=opts.get("model", "qwen2.5:3b"),
                               base_url=opts.get("base_url", "http://127.0.0.1:11434"),
                               timeout=opts.get("timeout_seconds", 30))
            try:
                await model.check()
                print(await model.translate("Increasing the firing angle delays conduction."))
            finally:
                await model.close()
        try:
            asyncio.run(check_local())
        except Exception as exc:
            parser.exit(1, str(exc) + "\n")
        return
    stop = threading.Event()
    updates = queue.Queue(maxsize=1)
    system = None

    def emit(snapshot):
        if args.headless:
            print(json.dumps(snapshot, ensure_ascii=False), flush=True)
        try:
            updates.put_nowait(snapshot)
        except queue.Full:
            try: updates.get_nowait()
            except queue.Empty: pass
            try: updates.put_nowait(snapshot)
            except queue.Full: pass

    def status(message):
        print(message, flush=True)
        emit({"status": message})

    if not args.demo:
        if sys.platform != "win32":
            parser.error("Live WASAPI capture requires Windows 10/11; use --demo here")
        from presense.runtime import load_upstream, build_system
        upstream = load_upstream()
        devices = upstream.list_audio_devices(host_api="wasapi")
        loopbacks = [d for d in devices if d.get("isLoopback")]
        if args.list_devices:
            for device in loopbacks:
                print(f"{device['index']}: {device['name']}")
            return
        if args.device is None:
            for device in loopbacks:
                print(f"{device['index']}: {device['name']}")
            args.device = int(input("Choose the loopback matching your current speakers/headphones: "))
        device = next((d for d in loopbacks if d["index"] == args.device), None)
        if device is None:
            parser.error("Choose a listed WASAPI loopback device")
        config["websocket"]["port"] = args.port
        for section in ("openai", "deepl"):
            config[section]["api_key"] = upstream.decode_api_key(config[section].get("api_key", ""))
        mode = config.get("translation", {}).get("translation_model")
        if mode not in ("openai", "deepl", "ollama"):
            parser.error("V0 supports Whisper + openai/deepl/ollama translation")
        if mode != "ollama" and not config["openai"]["api_key"]:
            parser.error("Set OPENAI_API_KEY or choose --local for Ollama")
        if mode == "deepl" and not config["deepl"]["api_key"]:
            parser.error("DeepL translation selected but DEEPL_API_KEY is empty")
        system = build_system(upstream, config, device, emit, status)

    def worker():
        try:
            if args.demo:
                from presense.demo import run_demo
                asyncio.run(run_demo(emit, stop, args.port))
            else:
                system.start()
                while not stop.wait(0.2):
                    if system.state in (upstream.RouteState.ERROR, upstream.RouteState.IDLE):
                        status("Capture ended; inspect console for errors")
                        break
        except Exception as exc:
            status("Startup error: " + type(exc).__name__ + "; inspect configuration/port")
            import traceback
            traceback.print_exc()
        finally:
            if system:
                system.stop()
            stop.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    if args.seconds > 0:
        timer = threading.Timer(args.seconds, stop.set)
        timer.daemon = True
        timer.start()

    if args.headless:
        try:
            while not stop.wait(0.2): pass
        except KeyboardInterrupt:
            stop.set()
        thread.join(timeout=15)
        return

    import tkinter as tk
    root = tk.Tk()
    root.title("PreSense V0" + (" — DEMO" if args.demo else ""))
    root.geometry("800x820")
    root.configure(bg="#101319")
    root.minsize(540, 550)
    tk.Label(root, text="PreSense", font=("Segoe UI", 27, "bold"),
             fg="white", bg="#101319").pack(anchor="w", padx=28, pady=(22, 3))
    label = tk.Label(root, text="DEMO · 固定脚本" if args.demo else "Starting audio and models…",
                     fg="#b6c5d5", bg="#101319", wraplength=720, anchor="w")
    label.pack(anchor="w", padx=28, pady=(0, 12))
    history_frame = tk.Frame(root, bg="#191e27", padx=15, pady=10)
    history_frame.pack(fill="both", expand=True, padx=28, pady=5)
    tk.Label(history_frame, text="CONFIRMED · 已确认 · 保留最近 500 段，可向上回看",
             fg="white", bg="#191e27", font=("Segoe UI", 10, "bold")).pack(anchor="w")
    follow = tk.BooleanVar(value=True)
    tk.Checkbutton(history_frame, text="自动跟随最新字幕（取消勾选可停留阅读）",
                   variable=follow, bg="#191e27", fg="#b6c5d5",
                   selectcolor="#101319", activebackground="#191e27").pack(anchor="w")
    text_frame = tk.Frame(history_frame, bg="#191e27")
    text_frame.pack(fill="both", expand=True)
    transcript = tk.Text(text_frame, wrap="word", height=12, width=1,
                         bg="#191e27", fg="white", relief="flat", borderwidth=0,
                         font=("Segoe UI", 13), state="disabled", padx=2, pady=5)
    scrollbar = tk.Scrollbar(text_frame, command=transcript.yview)
    transcript.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    transcript.pack(side="left", fill="both", expand=True)
    transcript.tag_configure("translation", font=("Segoe UI", 13), spacing3=14)
    transcript.tag_configure("original", spacing3=5)
    rendered_history = []

    def latest():
        follow.set(True)
        transcript.see("end")

    tk.Button(history_frame, text="回到最新 ↓", command=latest).pack(anchor="e")

    def render_history(items):
        nonlocal rendered_history
        if items == rendered_history:
            return
        at_bottom = transcript.yview()[1] >= 0.995
        should_follow = follow.get() and at_bottom
        if not at_bottom:
            follow.set(False)
        # Anchor to an utterance and its wrapped-line offset, even when an
        # earlier translation arrives or the bounded history evicts a row.
        top = transcript.index("@0,0")
        anchor = None
        offset = 0
        for row in rendered_history:
            mark = "row_" + str(row["id"])
            if transcript.compare(mark, "<=", top):
                anchor = mark
                offset = (transcript.count(mark, top, "displaylines") or (0,))[0]
        transcript.configure(state="normal")
        transcript.delete("1.0", "end")
        for mark in transcript.mark_names():
            if mark.startswith("row_"):
                transcript.mark_unset(mark)
        for row in items:
            mark = "row_" + str(row["id"])
            transcript.mark_set(mark, "end-1c")
            transcript.mark_gravity(mark, "left")
            transcript.insert("end", row["text"] + "\n", "original")
            transcript.insert("end", (row["translation"] or "翻译中…") + "\n\n", "translation")
        transcript.configure(state="disabled")
        if should_follow:
            transcript.see("end")
        elif anchor in transcript.mark_names():
            transcript.yview(anchor + " + " + str(offset) + " display lines")
        else:
            transcript.yview("1.0")
        rendered_history = items

    fields = {}
    for key, title, color in (("live", "LIVE · 识别中", "#d2d7df"),
                              ("prediction", "PREDICTION · AI 推测，尚未说出", "#939ca9")):
        frame = tk.Frame(root, bg="#191e27", padx=15, pady=10)
        frame.pack(fill="both", expand=True, padx=28, pady=5)
        tk.Label(frame, text=title, fg=color, bg="#191e27", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        body = tk.Frame(frame, bg="#191e27", height=150)
        body.pack(fill="both", expand=True)
        body.grid_propagate(False)
        body.columnconfigure(0, weight=1)
        for row, name in enumerate((key, key + "_translation")):
            body.rowconfigure(row, weight=1, uniform="languages")
            widget = tk.Text(body, height=3, width=1, wrap="word",
                             fg=color, bg="#191e27", relief="flat",
                             font=("Segoe UI", 13), state="disabled")
            widget.grid(row=row, column=0, sticky="nsew", pady=3)
            scroll = tk.Scrollbar(body, command=widget.yview)
            scroll.grid(row=row, column=1, sticky="ns")
            widget.configure(yscrollcommand=scroll.set)
            fields[name] = widget
    live_note = tk.Label(root, text="LIVE 为草稿 · 中文最多每 2 秒修订一次",
                         fg="#b6c5d5", bg="#101319")
    live_note.pack(anchor="w", padx=28)
    latest_snap = {}
    shown = {}
    last_translation_at = 0.0
    display_uid = None

    def set_field(key, value):
        value = value or "—"
        if shown.get(key) == value:
            return
        widget = fields[key]
        top = widget.index("@0,0")
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")
        widget.yview(top)
        shown[key] = value

    def close():
        stop.set()
        label.configure(text="Stopping…")
        def wait_closed():
            if thread.is_alive(): root.after(100, wait_closed)
            else: root.destroy()
        wait_closed()

    tk.Button(root, text="停止 / Stop", command=close, padx=24).pack(pady=14)
    root.protocol("WM_DELETE_WINDOW", close)

    def poll():
        nonlocal last_translation_at, display_uid
        try:
            snap = updates.get_nowait()
            latest_snap.update(snap)
            label.configure(text=snap.get("status", ""))
            if "transcript" in snap:
                render_history(snap["transcript"])
        except queue.Empty:
            pass
        for key in fields:
            if key != "live_translation" and key in latest_snap:
                set_field(key, latest_snap[key])
        rows = latest_snap.get("transcript", [])
        uid = (latest_snap.get("session_id"), rows[-1]["id"] if rows else 0)
        if uid != display_uid:
            set_field("live_translation", "")
            last_translation_at = 0.0
            display_uid = uid
        value = latest_snap.get("live_translation", "")
        # Status belongs outside the paragraph: it must not change line wrapping.
        value = value.replace(" ⟨后续内容翻译中…⟩", "")
        now = time.monotonic()
        if not latest_snap.get("live"):
            set_field("live_translation", "")
            last_translation_at = 0.0
        elif value and value != "翻译中…":
            if now - last_translation_at >= 2.0:
                set_field("live_translation", value)
                last_translation_at = now
            live_note.configure(text="LIVE 为草稿 · 中文最多每 2 秒修订一次")
        else:
            # Keep readable draft while its replacement is being translated.
            live_note.configure(text="LIVE 中文修订中 · 暂时保留上一版草稿")
        root.after(50, poll)

    poll()
    root.mainloop()


if __name__ == "__main__":
    # RealtimeSTT uses multiprocessing on Windows.
    import multiprocessing
    multiprocessing.freeze_support()
    os.chdir(ROOT)
    main()

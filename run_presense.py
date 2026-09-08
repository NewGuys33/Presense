"""Windows desktop entry. --demo works without audio models or API keys."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import queue
import sys
import threading

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
    root.geometry("800x630")
    root.configure(bg="#101319")
    root.minsize(540, 550)
    tk.Label(root, text="PreSense", font=("Segoe UI", 27, "bold"),
             fg="white", bg="#101319").pack(anchor="w", padx=28, pady=(22, 3))
    label = tk.Label(root, text="DEMO · 固定脚本" if args.demo else "Starting audio and models…",
                     fg="#b6c5d5", bg="#101319", wraplength=720, anchor="w")
    label.pack(anchor="w", padx=28, pady=(0, 12))
    fields = {}
    for key, title, color in (("confirmed", "CONFIRMED · 已确认", "#ffffff"),
                              ("live", "LIVE · 识别中", "#d2d7df"),
                              ("prediction", "PREDICTION · AI 推测，尚未说出", "#939ca9")):
        frame = tk.Frame(root, bg="#191e27", padx=15, pady=10)
        frame.pack(fill="both", expand=True, padx=28, pady=5)
        tk.Label(frame, text=title, fg=color, bg="#191e27", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        for name, size in ((key, 13), (key + "_translation", 17)):
            widget = tk.Label(frame, text="—", fg=color, bg="#191e27", justify="left",
                              anchor="w", wraplength=710, font=("Segoe UI", size))
            widget.pack(fill="x", pady=2)
            fields[name] = widget

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
        try:
            snap = updates.get_nowait()
            label.configure(text=snap.get("status", ""))
            for key, widget in fields.items():
                if key in snap: widget.configure(text=snap[key] or "—")
        except queue.Empty:
            pass
        root.after(50, poll)

    def resize(event):
        if event.widget is root:
            for widget in fields.values(): widget.configure(wraplength=max(200, event.width-95))
    root.bind("<Configure>", resize)
    poll()
    root.mainloop()


if __name__ == "__main__":
    # RealtimeSTT uses multiprocessing on Windows.
    import multiprocessing
    multiprocessing.freeze_support()
    os.chdir(ROOT)
    main()

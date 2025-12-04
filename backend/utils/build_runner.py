# utils/build_runner.py
import json
import subprocess
import platform
from datetime import datetime, timezone
from flask import current_app

# IMPORTANT: do NOT import app or models directly here to avoid circular imports.
# We receive `app` and `socketio` instances from the caller (create_app/socketio.start_background_task).

def run_command_and_stream(build_id, step_index, cmd, app, socketio):
    if not cmd:
        return 0

    # Windows adjustment
    if platform.system() == "Windows":
        cmd = f"cmd /c {cmd}"

    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        print(f"[Build {build_id} | Step {step_index}] Failed to start: {e}")
        return 1

    buffer = []          # batch DB logs
    emit_cooldown = 0    # throttle socket emissions

    # read lines and stream
    for line in iter(proc.stdout.readline, ""):
        if not line:
            break

        text_line = line.rstrip("\n")
        print(f"[Build {build_id} | Step {step_index}]: {text_line}")

        # Add to buffer (we commit every 15 logs)
        buffer.append(text_line)
        if len(buffer) >= 15:
            with app.app_context():
                from models import db, BuildLog
                for log_line in buffer:
                    db.session.add(BuildLog(build_id=build_id, step_index=step_index, text=log_line))
                db.session.commit()
            buffer.clear()

        # ---- FIX 1: throttle socket.io emits ----
        emit_cooldown += 1
        if emit_cooldown >= 5:   # send every 5 lines (safe)
            try:
                socketio.emit(
                    "build_log",
                    {"build_id": build_id, "step_index": step_index, "text": text_line},
                )
            except Exception:
                pass
            emit_cooldown = 0

    # flush remaining logs
    if buffer:
        with app.app_context():
            from models import db, BuildLog
            for log_line in buffer:
                db.session.add(BuildLog(build_id=build_id, step_index=step_index, text=log_line))
            db.session.commit()

    proc.stdout.close()
    rc = proc.wait()
    print(f"[Build {build_id} | Step {step_index}] Return code {rc}")
    return rc


def run_build_thread(build_id, pipeline_config_json, app, socketio):
    # app: the Flask app instance
    # socketio: the SocketIO instance created in app.py
    with app.app_context():
        from models import db, Build  # local import to avoid circular import
        build = db.session.get(Build, build_id)
        if not build:
            print(f"[Build {build_id}] Not found in DB")
            return

        build.status = "running"
        db.session.commit()

    # notify clients
    try:
        socketio.emit("build_status_update", {"build_id": build_id, "status": "running"})
    except Exception:
        pass

    try:
        config = json.loads(pipeline_config_json or "{}")
        steps = config.get("steps", [])

        total_steps = len(steps) or 1

        for index, step in enumerate(steps):
            cmd = step.get("cmd")
            try:
                socketio.emit(
                    "build_step_start",
                    {"build_id": build_id, "step_index": index, "cmd": cmd},
                )
            except Exception:
                pass

            rc = run_command_and_stream(build_id, index, cmd, app, socketio)

            try:
                socketio.emit(
                    "build_progress",
                    {"build_id": build_id, "progress": int(((index + 1) / total_steps) * 100)},
                )
            except Exception:
                pass

            if rc != 0:
                with app.app_context():
                    from models import db, Build
                    build = db.session.get(Build, build_id)
                    build.status = "failed"
                    build.finished_at = datetime.now(timezone.utc)
                    db.session.commit()

                try:
                    socketio.emit("build_finished", {"build_id": build_id, "status": "failed"})
                except Exception:
                    pass
                return

        with app.app_context():
            from models import db, Build
            build = db.session.get(Build, build_id)
            build.status = "success"
            build.finished_at = datetime.now(timezone.utc)
            db.session.commit()

        try:
            socketio.emit("build_finished", {"build_id": build_id, "status": "success"})
        except Exception:
            pass

    except Exception as e:
        with app.app_context():
            from models import db, Build
            build = db.session.get(Build, build_id)
            if build:
                build.status = "failed"
                build.finished_at = datetime.now(timezone.utc)
                db.session.commit()

        try:
            socketio.emit(
                "build_finished", {"build_id": build_id, "status": "failed", "error": str(e)}
            )
        except Exception:
            pass

# ==========================================================
# FIX: Apply eventlet patch FIRST before importing anything
# ==========================================================
import eventlet
eventlet.monkey_patch()

# ==========================================================
# Imports
# ==========================================================
import os
import json
import subprocess
import platform
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_socketio import SocketIO
from flask_cors import CORS

# ==========================================================
# Initialize
# ==========================================================
db = SQLAlchemy()
socketio = SocketIO(cors_allowed_origins="*", async_mode="eventlet")

# ==========================================================
# Models
# ==========================================================
class Pipeline(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    description = db.Column(db.Text)
    config_json = db.Column(db.Text)
    builds = db.relationship("Build", backref="pipeline", lazy=True, cascade="all, delete-orphan")

    def to_dict(self, include_stats=False):
        try:
            config = json.loads(self.config_json or "{}")
        except Exception:
            config = {}
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "config_json": config,
        }
        if include_stats:
            data["stats"] = {
                "running": Build.query.filter_by(pipeline_id=self.id, status="running").count(),
                "success": Build.query.filter_by(pipeline_id=self.id, status="success").count(),
                "failed": Build.query.filter_by(pipeline_id=self.id, status="failed").count(),
            }
        return data


class Build(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pipeline_id = db.Column(db.Integer, db.ForeignKey("pipeline.id"))
    status = db.Column(db.String(50), default="queued")
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)
    logs = db.relationship("BuildLog", backref="build", lazy=True)

    def to_dict(self):
        duration = None
        if self.started_at and self.finished_at:
            duration = (self.finished_at - self.started_at).total_seconds()
        return {
            "id": self.id,
            "pipeline_id": self.pipeline_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration": duration,
        }


class BuildLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    build_id = db.Column(db.Integer, db.ForeignKey("build.id"))
    step_index = db.Column(db.Integer)
    text = db.Column(db.Text)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(150))


# ==========================================================
# App Factory
# ==========================================================
def create_app():
    app = Flask(__name__)
    CORS(app)

    instance_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance")
    os.makedirs(instance_dir, exist_ok=True)

    db_path = os.path.join(instance_dir, "pipeline.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}?check_same_thread=False"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "super-secret-key"

    db.init_app(app)
    JWTManager(app)
    socketio.init_app(app, cors_allowed_origins="*")

    with app.app_context():
        db.create_all()

    # ================== PIPELINE ROUTES ==================
    @app.route("/api/pipelines", methods=["GET"], strict_slashes=False)
    def get_pipelines():
        pipelines = Pipeline.query.all()
        return jsonify([p.to_dict(include_stats=True) for p in pipelines])

    @app.route("/api/pipelines", methods=["POST"], strict_slashes=False)
    def create_pipeline():
        data = request.json
        if not data.get("name") or not data.get("config_json"):
            return jsonify({"error": "Missing name or config_json"}), 400

        pipeline = Pipeline(
            name=data["name"],
            description=data.get("description", ""),
            config_json=json.dumps(data.get("config_json")),
        )
        db.session.add(pipeline)
        db.session.commit()
        return jsonify(pipeline.to_dict(include_stats=True)), 201

    @app.route("/api/pipelines/<int:pipeline_id>", methods=["GET"], strict_slashes=False)
    def get_pipeline(pipeline_id):
        pipeline = db.session.get(Pipeline, pipeline_id)
        if not pipeline:
            return jsonify({"error": "Pipeline not found"}), 404
        return jsonify(pipeline.to_dict(include_stats=True))

    @app.route("/api/pipelines/<int:pipeline_id>/run", methods=["POST"], strict_slashes=False)
    def run_pipeline(pipeline_id):
        pipeline = db.session.get(Pipeline, pipeline_id)
        if not pipeline:
            return jsonify({"error": "Pipeline not found"}), 404

        build = Build(
            pipeline_id=pipeline.id,
            status="queued",
            started_at=datetime.now(timezone.utc),
        )
        db.session.add(build)
        db.session.commit()

        socketio.start_background_task(run_build_thread, build.id, pipeline.config_json, app, socketio)
        return jsonify({"message": "Pipeline started", "build_id": build.id})

    @app.route("/api/pipelines/<int:pipeline_id>", methods=["DELETE"], strict_slashes=False)
    def delete_pipeline(pipeline_id):
        pipeline = db.session.get(Pipeline, pipeline_id)
        if not pipeline:
            return jsonify({"error": "Pipeline not found"}), 404

        builds = Build.query.filter_by(pipeline_id=pipeline_id).all()
        for b in builds:
            db.session.delete(b)

        db.session.delete(pipeline)
        db.session.commit()

        return jsonify({"message": f"Pipeline {pipeline_id} deleted successfully"}), 200

    # ================== BUILDS ROUTES ==================
    @app.route("/api/builds", methods=["GET"], strict_slashes=False)
    def list_builds():
        builds = Build.query.order_by(Build.started_at.desc()).limit(20).all()
        return jsonify([b.to_dict() for b in builds])

    @app.route("/api/builds/<int:build_id>/logs", methods=["GET"], strict_slashes=False)
    def get_build_logs(build_id):
        build = db.session.get(Build, build_id)
        if not build:
            return jsonify({"error": "Build not found"}), 404
        logs = BuildLog.query.filter_by(build_id=build_id).order_by(BuildLog.id.asc()).all()
        return jsonify([
            {"step_index": l.step_index, "text": l.text, "timestamp": datetime.now().isoformat()}
            for l in logs
        ])

    return app


# ==========================================================
# Build Execution
# ==========================================================
def run_command_and_stream(build_id, step_index, cmd, app, socketio):
    if not cmd:
        return 0

    if platform.system() == "Windows":
        cmd = f"cmd /c {cmd}"

    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
    except Exception as e:
        print(f"[Build {build_id} | Step {step_index}] Error starting command: {e}")
        return 1

    for line in iter(proc.stdout.readline, ""):
        text_line = line.rstrip("\n")
        print(f"[Build {build_id} | Step {step_index}]: {text_line}")
        with app.app_context():
            log = BuildLog(build_id=build_id, step_index=step_index, text=text_line)
            db.session.add(log)
            db.session.commit()
        socketio.emit("build_log", {"build_id": build_id, "step_index": step_index, "text": text_line})

        # 🚨 Detect PyGuard output in real-time
        if "[pyguard] High-risk detected" in text_line:
            print(f"[Build {build_id} | Step {step_index}] ❌ PyGuard found HIGH-risk vulnerabilities — stopping pipeline.")
            proc.kill()
            return 1

    proc.stdout.close()
    rc = proc.wait()
    print(f"[Build {build_id} | Step {step_index}] Finished with return code {rc}")

    # ✅ Stop pipeline on PyGuard error
    if "pyguard_embedding.py" in cmd.lower() and rc != 0:
        print(f"[Build {build_id} | Step {step_index}] ❌ PyGuard scan failed — vulnerabilities found.")
        return 1

    return rc


def run_build_thread(build_id, pipeline_config_json, app, socketio):
    with app.app_context():
        build = db.session.get(Build, build_id)
        build.status = "running"
        db.session.commit()
        socketio.emit("build_status_update", {"build_id": build.id, "status": "running"})

    try:
        steps = json.loads(pipeline_config_json).get("steps", [])
        for i, step in enumerate(steps):
            cmd = step.get("cmd")
            socketio.emit("build_step_start", {"build_id": build_id, "step_index": i, "cmd": cmd})
            rc = run_command_and_stream(build_id, i, cmd, app, socketio)
            socketio.emit("build_progress", {"build_id": build_id, "progress": int(((i + 1) / len(steps)) * 100)})

            # 🚨 Stop pipeline immediately on any failure
            if rc != 0:
                with app.app_context():
                    build.status = "failed"
                    build.finished_at = datetime.now(timezone.utc)
                    db.session.commit()

                socketio.emit("build_finished", {
                    "build_id": build_id,
                    "status": "failed",
                    "error": "PyGuard scan detected high-risk vulnerabilities."
                        if "pyguard" in cmd.lower()
                        else f"Command failed with exit code {rc}"
                })
                print(f"[Build {build_id}] ❌ Pipeline stopped at step {i} due to failure.")
                return

        # ✅ All steps succeeded
        with app.app_context():
            build.status = "success"
            build.finished_at = datetime.now(timezone.utc)
            db.session.commit()

        socketio.emit("build_finished", {"build_id": build_id, "status": "success"})
        print(f"[Build {build_id}] ✅ Pipeline completed successfully.")

    except Exception as e:
        with app.app_context():
            build = db.session.get(Build, build_id)
            build.status = "failed"
            build.finished_at = datetime.now(timezone.utc)
            db.session.commit()
        socketio.emit("build_finished", {"build_id": build_id, "status": "failed", "error": str(e)})
        print(f"[Build {build_id}] ❌ Exception during pipeline: {e}")


# ==========================================================
# Main
# ==========================================================
if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        if Pipeline.query.count() == 0:
            steps = [
                {"cmd": "echo Step 1: Build started"},
                {"cmd": "echo Step 2: Running tests"},
                {"cmd": "echo Step 3: Deploy complete"},
            ]
            test_pipeline = Pipeline(
                name="Test Pipeline",
                description="Demo pipeline for testing",
                config_json=json.dumps({"steps": steps}),
            )
            db.session.add(test_pipeline)
            db.session.commit()
            print("✅ Created default pipeline")

    print("🚀 Running on http://127.0.0.1:5000 with live dashboard updates")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False)

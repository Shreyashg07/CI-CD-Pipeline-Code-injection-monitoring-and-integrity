# app.py
import eventlet
eventlet.monkey_patch()

import os
import json
from datetime import datetime, timezone
from typing import Optional
from collections import Counter

from flask import Flask, jsonify, request, send_from_directory
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_socketio import SocketIO

from models import db, Pipeline, Build, BuildLog, User
from utils.build_runner import run_build_thread

socketio = SocketIO(cors_allowed_origins="*", async_mode="eventlet")


def find_latest_json_report(reports_dir: str) -> Optional[str]:
    """Return path to latest .json file in reports dir."""
    if not os.path.isdir(reports_dir):
        return None
    json_files = [
        os.path.join(reports_dir, f)
        for f in os.listdir(reports_dir)
        if f.lower().endswith(".json")
    ]
    if not json_files:
        return None
    json_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return json_files[0]


def create_app():
    app = Flask(__name__, static_folder=None)
    CORS(app)

    instance_dir = os.path.join(os.path.dirname(__file__), "instance")
    os.makedirs(instance_dir, exist_ok=True)

    db_path = os.path.join(instance_dir, "pipeline.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}?check_same_thread=False"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JWT_SECRET_KEY"] = "super-secret"

    db.init_app(app)
    JWTManager(app)
    socketio.init_app(app, cors_allowed_origins="*")
    app.socketio = socketio

    with app.app_context():
        db.create_all()

    # -------------------------------
    # PIPELINE ROUTES
    # -------------------------------
    @app.route("/api/pipelines", methods=["GET"])
    def get_pipelines():
        """Return pipelines with latest build info (status, runtime)."""
        pipelines = []
        for p in Pipeline.query.all():
            last_build = (
                Build.query.filter_by(pipeline_id=p.id)
                .order_by(Build.id.desc())
                .first()
            )

            status = "unknown"
            runtime = "N/A"

            if last_build:
                status = last_build.status or "unknown"
                if last_build.started_at:
                    try:
                        end_time = last_build.finished_at or datetime.now(timezone.utc)
                        runtime_min = int((end_time - last_build.started_at).total_seconds() / 60)
                        runtime = f"{runtime_min} min"
                    except Exception as e:
                        print(f"⚠️ Runtime calc error for {p.name}: {e}")

            pipelines.append({
                "id": p.id,
                "name": p.name,
                "status": status,
                "runtime": runtime,
            })

        return jsonify(pipelines)

    @app.route("/api/pipelines", methods=["POST"])
    def create_pipeline():
        data = request.get_json() or {}
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

    @app.route("/api/pipelines/<int:pipeline_id>/run", methods=["POST"])
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

        socketio.start_background_task(
            run_build_thread,
            build.id,
            pipeline.config_json,
            app,
            socketio,
        )
        return jsonify({"build_id": build.id}), 202

    @app.route("/api/pipelines/<int:pipeline_id>", methods=["DELETE"])
    def delete_pipeline(pipeline_id):
        pipeline = db.session.get(Pipeline, pipeline_id)
        if not pipeline:
            return jsonify({"error": "Pipeline not found"}), 404
        db.session.delete(pipeline)
        db.session.commit()
        return jsonify({"message": f"Pipeline {pipeline_id} deleted"}), 200

    # -------------------------------
    # BUILD ROUTES
    # -------------------------------
    @app.route("/api/builds", methods=["GET"])
    def list_builds():
        builds = Build.query.order_by(Build.started_at.desc().nullslast()).limit(50).all()
        return jsonify([b.to_dict() for b in builds])

    @app.route("/api/builds/<int:build_id>/logs", methods=["GET"])
    def get_build_logs(build_id):
        build = db.session.get(Build, build_id)
        if not build:
            return jsonify({"error": "Build not found"}), 404
        logs = (
            BuildLog.query.filter_by(build_id=build_id)
            .order_by(BuildLog.id.asc())
            .all()
        )
        return jsonify(
            [
                {
                    "step_index": l.step_index,
                    "text": l.text,
                    "timestamp": l.timestamp.isoformat() if getattr(l, "timestamp", None) else None,
                }
                for l in logs
            ]
        )

    # -------------------------------
    # DASHBOARD DATA ROUTE
    # -------------------------------
    @app.route("/api/dashboard-data", methods=["GET"])
    def dashboard_data():
        pipelines = []
        for p in Pipeline.query.all():
            last_build = (
                Build.query.filter_by(pipeline_id=p.id)
                .order_by(Build.id.desc())
                .first()
            )
            status = last_build.status if last_build else "unknown"
            runtime = "N/A"
            if last_build and last_build.started_at:
                try:
                    start_time = last_build.started_at
                    now = datetime.now(timezone.utc)
                    if (start_time.tzinfo is None and now.tzinfo is not None) or \
                       (start_time.tzinfo is not None and now.tzinfo is None):
                        start_time = start_time.replace(tzinfo=None)
                        now = now.replace(tzinfo=None)
                    runtime_minutes = int((now - start_time).total_seconds() // 60)
                    runtime = f"{runtime_minutes} min"
                except Exception as e:
                    print(f"⚠️ Runtime calc error for pipeline {p.id}: {e}")
                    runtime = "N/A"

            pipelines.append({
                "id": p.id,
                "name": p.name,
                "status": status,
                "runtime": runtime,
            })

        logs = []
        for log in BuildLog.query.order_by(BuildLog.id.desc()).limit(5).all():
            text_value = log.text.strip() if getattr(log, "text", None) else log.text
            logs.append({
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "text": text_value,
            })

        reports_dir = os.path.join(os.path.dirname(__file__), "reports")
        latest_report = find_latest_json_report(reports_dir)
        risk_score = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        threat_categories = Counter()

        if latest_report:
            try:
                with open(latest_report, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "details" in data:
                    for item in data.get("details", []):
                        sev = (item.get("risk") or item.get("severity") or "").upper()
                        if sev in risk_score:
                            risk_score[sev] += 1
                        cat = item.get("category", "unknown")
                        threat_categories[cat] += 1
            except Exception as e:
                print(f"Error reading/parsing report '{latest_report}': {e}")
        else:
            print("No JSON report found in reports/ directory.")

        return jsonify({
            "pipelines": pipelines,
            "logs": logs,
            "risk_score": risk_score,
            "threat_categories": dict(threat_categories),
            "report_file": latest_report or None
        })

    # -------------------------------
    # REPORTS ROUTE (REALTIME DATA)
    # -------------------------------
    @app.route("/api/reports", methods=["GET"])
    def list_reports():
        reports_dir = os.path.join(os.path.dirname(__file__), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        reports = []

        for filename in os.listdir(reports_dir):
            if filename.endswith(".json") or filename.endswith(".html"):
                file_path = os.path.join(reports_dir, filename)
                created_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                report_type = "Security"
                if "performance" in filename.lower():
                    report_type = "Performance"
                elif "compliance" in filename.lower():
                    report_type = "Compliance"

                fmt = "HTML" if filename.endswith(".html") else "JSON"

                reports.append({
                    "name": filename,
                    "type": report_type,
                    "format": fmt,
                    "generated_at": created_time.strftime("%d/%m/%Y"),
                    "view_url": f"http://127.0.0.1:5000/api/reports/view/{filename}",
                    "download_url": f"http://127.0.0.1:5000/api/reports/download/{filename}",
                })

        reports.sort(key=lambda x: x["generated_at"], reverse=True)
        return jsonify({"reports": reports})

    @app.route("/api/reports/download/<filename>", methods=["GET"])
    def download_report(filename):
        reports_dir = os.path.join(os.path.dirname(__file__), "reports")
        if not os.path.exists(os.path.join(reports_dir, filename)):
            return jsonify({"error": "Report not found"}), 404
        return send_from_directory(reports_dir, filename, as_attachment=True)

    @app.route("/api/reports/view/<filename>", methods=["GET"])
    def view_report(filename):
        reports_dir = os.path.join(os.path.dirname(__file__), "reports")
        if not os.path.exists(os.path.join(reports_dir, filename)):
            return jsonify({"error": "Report not found"}), 404
        return send_from_directory(reports_dir, filename)

    return app


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

    print("🚀 Backend starting on http://127.0.0.1:5000")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, use_reloader=False)

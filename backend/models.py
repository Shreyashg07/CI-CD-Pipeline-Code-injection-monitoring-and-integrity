# models.py
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    role = db.Column(db.String(32), default="dev")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Pipeline(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=True)
    config_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    builds = db.relationship("Build", backref="pipeline", lazy=True, cascade="all, delete-orphan")

    def to_dict(self, include_stats=False):
        import json
        try:
            config = json.loads(self.config_json or "{}")
        except Exception:
            config = {}
        data = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "config_json": config,
            "created_at": self.created_at.isoformat() if self.created_at else None,
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
    pipeline_id = db.Column(db.Integer, db.ForeignKey("pipeline.id"), nullable=False)
    status = db.Column(db.String(32), default="queued")  # queued, running, success, failed
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    logs = db.relationship("BuildLog", backref="build", lazy=True, cascade="all, delete-orphan")

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
    build_id = db.Column(db.Integer, db.ForeignKey("build.id"), nullable=False)
    step_index = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    text = db.Column(db.Text, nullable=False)

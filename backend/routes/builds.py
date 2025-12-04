from flask import Blueprint, jsonify
from models import Build, BuildLog, Pipeline

bp = Blueprint('builds', __name__)

# ✅ List all builds with their pipeline name
@bp.route('/', methods=['GET'])
def list_builds():
    builds = Build.query.order_by(Build.started_at.desc().nullslast()).all()
    out = []
    for b in builds:
        pipeline = Pipeline.query.get(b.pipeline_id)
        out.append({
            'id': b.id,
            'pipeline_id': b.pipeline_id,
            'pipeline_name': pipeline.name if pipeline else None,
            'status': b.status,
            'started_at': b.started_at.isoformat() if b.started_at else None,
            'finished_at': b.finished_at.isoformat() if b.finished_at else None
        })
    return jsonify(out)


# ✅ Fetch logs for a specific build
@bp.route('/<int:build_id>/logs', methods=['GET'])
def build_logs(build_id):
    logs = BuildLog.query.filter_by(build_id=build_id).order_by(BuildLog.timestamp).all()
    out = [{
        'timestamp': l.timestamp.isoformat(),
        'text': l.text,
        'step_index': l.step_index
    } for l in logs]
    return jsonify(out)

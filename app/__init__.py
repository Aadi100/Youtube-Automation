"""Clip Studio.

    app/models        M  MongoEngine documents (users, games, clips, videos, jobs ...) and their data access
    app/views         V  what the browser gets: the dashboard, HTML templates, JSON serializers
    app/controllers   C  Flask blueprints: the HTTP endpoints (one module per area)
    app/services         business logic: job queue, uploads to YouTube, schedule, tokens, accounts, backups
    app/engine           the video pipeline: finding clips, AI moment picking, editing, commentary, captions, thumbnails
    app/utils            small helpers (.env file, process control, path safety)
"""
from flask import Flask


def create_app() -> Flask:
    """Build the Flask application: templates, shared hooks and every controller's blueprint."""
    from app import http
    from app.controllers import (admin_controller, approve_controller, auth_controller, clip_controller, game_controller, job_controller,
                                 schedule_controller, settings_controller, system_controller, video_controller, youtube_controller)

    flask_app = Flask("studio", template_folder="views/templates")
    http.install(flask_app)
    for ctrl in (system_controller, auth_controller, admin_controller, youtube_controller, settings_controller, schedule_controller,
                 game_controller, video_controller, approve_controller, clip_controller, job_controller):
        flask_app.register_blueprint(ctrl.bp)
    return flask_app

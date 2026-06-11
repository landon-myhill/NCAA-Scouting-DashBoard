"""
web — the Flask dashboard, split into focused modules.

    store.py     players.json / scarcity.json / history loading, profiles,
                 percentiles (read-only, cached at import)
    db.py        SQLite persistence (watchlist, notes, boards, draft toggles)
    charts.py    plotly radar JSON + stat formatting
    content.py   human copy: component explainers, archetype descriptions
    views.py     page routes (blueprint)
    api.py       JSON/CSV API routes (blueprint)

Import `app` from here (the root app.py entry point does exactly that).
"""

from flask import Flask

from core import BASE_DIR


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )

    from web import db
    db.init_db()
    app.teardown_appcontext(db.close_db)

    from web.api import api_bp
    from web.views import views_bp
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp)
    return app


app = create_app()

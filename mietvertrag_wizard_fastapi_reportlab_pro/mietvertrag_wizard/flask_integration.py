from __future__ import annotations

from pathlib import Path

from flask import Blueprint, render_template


def create_blueprint(*, url_prefix: str = "/mietvertrag", static_url_path: str = "/mietvertrag/static") -> Blueprint:
    pkg_dir = Path(__file__).resolve().parent

    bp = Blueprint(
        "mietvertrag_wizard",
        __name__,
        template_folder=str(pkg_dir / "templates"),
        static_folder=str(pkg_dir / "static"),
        url_prefix=url_prefix,
        static_url_path=static_url_path,
    )

    @bp.get("/")
    def wizard():
        return render_template(
            "mietvertrag_wizard/index.html",
            static_prefix=static_url_path + "/mietvertrag_wizard",
        )

    return bp

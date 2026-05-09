"""Flask routes for the calculator API."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

from flask import Blueprint, jsonify, request

from ..services.avalara_adapter import from_avalara_getquote
from ..services.calculator import calculate
from ..services.strategy import recommend

bp = Blueprint("calculator", __name__, url_prefix="/api")


def _to_json_safe(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(x) for x in obj]
    if isinstance(obj, set):
        return sorted(_to_json_safe(x) for x in obj)
    if isinstance(obj, dict):
        return {str(k): _to_json_safe(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        return _to_json_safe(asdict(obj))
    return obj


@bp.route("/health")
def health() -> Any:
    return jsonify({"status": "ok", "version": "0.1.0"})


@bp.route("/calculate", methods=["POST"])
def api_calculate() -> Any:
    """Accepts an Avalara getQuote-style payload and returns landed cost."""
    try:
        payload = request.get_json(force=True)
        consignment = from_avalara_getquote(payload)
        result = calculate(consignment)
        return jsonify(_to_json_safe(asdict(result)))
    except ValueError as exc:
        return jsonify({"error": str(exc), "type": "ValueError"}), 400
    except Exception as exc:
        return jsonify({"error": str(exc), "type": type(exc).__name__}), 500


@bp.route("/strategy", methods=["POST"])
def api_strategy() -> Any:
    """Returns ranked alternative shipping strategies."""
    try:
        payload = request.get_json(force=True)
        consignment = from_avalara_getquote(payload)
        strategies = recommend(consignment)
        return jsonify({
            "strategies": [
                {
                    "name": s.name,
                    "description": s.description,
                    "complexity": s.complexity,
                    "risk_notes": s.risk_notes,
                    "result": _to_json_safe(asdict(s.result)),
                }
                for s in strategies
            ]
        })
    except ValueError as exc:
        return jsonify({"error": str(exc), "type": "ValueError"}), 400
    except Exception as exc:
        return jsonify({"error": str(exc), "type": type(exc).__name__}), 500

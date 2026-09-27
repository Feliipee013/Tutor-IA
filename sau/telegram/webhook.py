"""Telegram webhook handler for Tutor-IA bot.

Receives Telegram updates via webhook, logs the raw update for debugging,
and returns an immediate "ok" acknowledgment without depending on LLM inference.
"""

import logging
import os

from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)

# Webhook configuration
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", "0.0.0.0")

app = Flask(__name__)


def process_update(update: dict) -> None:
    """Process a Telegram update.

    Logs the raw update for debugging and performs any necessary
    preprocessing. This function is designed to be side-effect friendly
    and does not block or depend on LLM inference.

    Args:
        update: Raw Telegram Update JSON dict
    """
    # Log the raw update for debugging/inspection
    logger.info("update_telegram: %s", update)


@app.route("/webhook", methods=["POST"])
def webhook():
    """Telegram webhook endpoint.

    Receives POST requests from Telegram containing updates.
    Logs the raw update and immediately returns "ok" acknowledgment.

    Returns:
        JSON response with "ok" status for Telegram
    """
    update = request.get_json(force=True, silent=True)
    if update is None:
        logger.warning("Received non-JSON or empty payload to webhook")
        return jsonify({"status": "error", "message": "invalid payload"}), 400

    # Process the update (log it, no LLM dependency)
    process_update(update)

    # Return immediate acknowledgment - this is FIXED, not model-dependent
    # This is the first half of what ADR-0001 requires: immediate receipt ack
    return jsonify({"status": "ok"})


def start_webhook(host: str = WEBHOOK_HOST, port: int = WEBHOOK_PORT) -> None:
    """Start the Telegram webhook server.

    Args:
        host: Host address to bind the webhook server
        port: Port to listen on for webhook requests
    """
    logger.info("Starting Telegram webhook on %s:%d", host, port)
    logger.info("Webhook endpoint: POST http://%s:%d/webhook", host, port)
    app.run(host=host, port=port)


if __name__ == "__main__":
    start_webhook()

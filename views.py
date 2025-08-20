# import logging
# import json

# from flask import Blueprint, request, jsonify, current_app

# from .decorators.security import signature_required
# from .utils.whatsapp_utils import (
#     process_whatsapp_message,
#     is_valid_whatsapp_message,
# )

# webhook_blueprint = Blueprint("webhook", __name__)


# def handle_message():
#     """
#     Handle incoming webhook events from the WhatsApp API.

#     This function processes incoming WhatsApp messages and other events,
#     such as delivery statuses. If the event is a valid message, it gets
#     processed. If the incoming payload is not a recognized WhatsApp event,
#     an error is returned.

#     Every message send will trigger 4 HTTP requests to your webhook: message, sent, delivered, read.

#     Returns:
#         response: A tuple containing a JSON response and an HTTP status code.
#     """
#     body = request.get_json()
#     # logging.info(f"request body: {body}")

#     # Check if it's a WhatsApp status update
#     if (
#         body.get("entry", [{}])[0]
#         .get("changes", [{}])[0]
#         .get("value", {})
#         .get("statuses")
#     ):
#         logging.info("Received a WhatsApp status update.")
#         return jsonify({"status": "ok"}), 200

#     try:
#         if is_valid_whatsapp_message(body):
#             process_whatsapp_message(body)
#             return jsonify({"status": "ok"}), 200
#         else:
#             # if the request is not a WhatsApp API event, return an error
#             return (
#                 jsonify({"status": "error", "message": "Not a WhatsApp API event"}),
#                 404,
#             )
#     except json.JSONDecodeError:
#         logging.error("Failed to decode JSON")
#         return jsonify({"status": "error", "message": "Invalid JSON provided"}), 400


# # Required webhook verifictaion for WhatsApp
# def verify():
#     # Parse params from the webhook verification request
#     mode = request.args.get("hub.mode")
#     token = request.args.get("hub.verify_token")
#     challenge = request.args.get("hub.challenge")
#     # Check if a token and mode were sent
#     if mode and token:
#         # Check the mode and token sent are correct
#         if mode == "subscribe" and token == current_app.config["VERIFY_TOKEN"]:
#             # Respond with 200 OK and challenge token from the request
#             logging.info("WEBHOOK_VERIFIED")
#             return challenge, 200
#         else:
#             # Responds with '403 Forbidden' if verify tokens do not match
#             logging.info("VERIFICATION_FAILED")
#             return jsonify({"status": "error", "message": "Verification failed"}), 403
#     else:
#         # Responds with '400 Bad Request' if verify tokens do not match
#         logging.info("MISSING_PARAMETER")
#         return jsonify({"status": "error", "message": "Missing parameters"}), 400


# @webhook_blueprint.route("/webhook", methods=["GET"])
# def webhook_get():
#     return verify()

# @webhook_blueprint.route("/webhook", methods=["POST"])
# @signature_required
# def webhook_post():
#     return handle_message()
##########################################################################################
#Desde aca lo que hace la IA
from flask import Blueprint, request, jsonify, current_app
import logging
import json

from .decorators.security import signature_required
from .utils.whatsapp_utils import (
    process_whatsapp_message,
    is_valid_whatsapp_message,
)

webhook_blueprint = Blueprint("webhook", __name__)


def handle_message():
    """
    Handle incoming webhook events from the WhatsApp API.
    Every inbound message puede gatillar varios callbacks (message, sent, delivered, read).
    """
    # ✅ JSON robusto: no explota si viene vacío/malformado
    body = request.get_json(force=True, silent=True) or {}
    # logging.info(f"request body: {body}")

    # Status updates (delivered/read/etc.)
    if (
        body.get("entry", [{}])[0]
        .get("changes", [{}])[0]
        .get("value", {})
        .get("statuses")
    ):
        logging.info("Received a WhatsApp status update.")
        # ✅ 200 siempre: no queremos reintentos de Meta
        return jsonify({"status": "ok"}), 200

    try:
        if is_valid_whatsapp_message(body):
            process_whatsapp_message(body)
            # ✅ 200 siempre, aunque la IA falle internamente (ya se maneja con logs)
            return jsonify({"status": "ok"}), 200
        else:
            # ❗️Antes devolvías 404: eso provoca reentregas del mismo evento
            logging.info("Ignoring non-WhatsApp or unsupported event")
            return jsonify({"status": "ok", "message": "ignored"}), 200
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON")
        # Aun así, 200 para evitar reintentos
        return jsonify({"status": "ok", "message": "invalid json"}), 200
    except Exception:
        # Cualquier fallo de negocio (OpenAI, etc.) NO debe tirar 500
        current_app.logger.exception("Unhandled error in handle_message")
        return jsonify({"status": "ok", "message": "handled"}), 200


# Required webhook verification for WhatsApp
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == current_app.config["VERIFY_TOKEN"]:
            logging.info("WEBHOOK_VERIFIED")
            return challenge, 200
        else:
            logging.info("VERIFICATION_FAILED")
            return jsonify({"status": "error", "message": "Verification failed"}), 403
    else:
        logging.info("MISSING_PARAMETER")
        return jsonify({"status": "error", "message": "Missing parameters"}), 400


@webhook_blueprint.route("/webhook", methods=["GET"])
def webhook_get():
    return verify()


@webhook_blueprint.route("/webhook", methods=["POST"])
@signature_required  # ⚠️ Mantén la verificación de firma (403 si es inválida)
def webhook_post():
    # ✅ Blindaje final: pase lo que pase adentro, respondemos 200 a Meta
    try:
        return handle_message()
    except Exception:
        current_app.logger.exception("Unhandled error in webhook_post")
        return jsonify({"status": "ok", "message": "handled"}), 200



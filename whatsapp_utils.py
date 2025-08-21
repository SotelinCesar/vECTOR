import logging
from flask import current_app, jsonify
import json
import requests
from app.services.openai_service import generate_response
import re

def log_http_response(response):
    logging.info(f"Status: {response.status_code}")
    logging.info(f"Content-type: {response.headers.get('content-type')}")
    logging.info(f"Body: {response.text}")

def get_text_message_input(recipient, text):
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

def send_message(data):
    headers = {
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
    }
    url = (
        f"https://graph.facebook.com/"
        f"{current_app.config['VERSION']}/"
        f"{current_app.config['PHONE_NUMBER_ID']}/messages"
    )
    logging.info(
        "Enviando a Graph: url=%s to=%s body=%.80s",
        url, data.get("to"), data.get("text", {}).get("body", "")
    )
    try:
        resp = requests.post(url, json=data, headers=headers, timeout=15)
        logging.info("Graph status=%s body=%s", resp.status_code, resp.text)
        resp.raise_for_status()
        return resp
    except requests.Timeout:
        logging.error("Timeout al enviar a Graph")
        return jsonify({"status": "error", "message": "Request timed out"}), 408
    except requests.RequestException as e:
        logging.error("Error al enviar a Graph: %s", e)
        if getattr(e, "response", None) is not None:
            logging.error("Graph resp=%s %s", e.response.status_code, e.response.text)
        return jsonify({"status": "error", "message": "Failed to send message"}), 500

def process_text_for_whatsapp(text):
    pattern = r"\【.*?\】"
    text = re.sub(pattern, "", text).strip()
    pattern = r"\*\*(.*?)\*\*"
    replacement = r"*\1*"
    whatsapp_style_text = re.sub(pattern, replacement, text)
    return whatsapp_style_text

PROCESSED_IDS=set()

def process_whatsapp_message(body):
    entry = body["entry"][0]["changes"][0]["value"]
    msgs = entry.get("messages", [])
    if not msgs:
        return
    msg = msgs[0]
    msg_id = msg["id"]
    if msg_id in PROCESSED_IDS:
        logging.info("Duplicado %s ignorado", msg_id)
        return
    PROCESSED_IDS.add(msg_id)
    wa_id = entry["contacts"][0]["wa_id"]
    name = entry["contacts"][0]["profile"]["name"]
    message_body = msg.get("text", {}).get("body", "")
    reply = generate_response(message_body,wa_id,name)
    reply = process_text_for_whatsapp(reply)
    data = get_text_message_input(wa_id,reply)
    send_message(data)

def is_valid_whatsapp_message(body):
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )
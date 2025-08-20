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


# def get_text_message_input(recipient, text):
#     return {
#         "messaging_product": "whatsapp",
#         "recipient_type": "individual",
#         "to": recipient,
#         "type": "text",
#         "text": {"preview_url": False, "body": text},
#     }

# def send_message(data):
#     url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{current_app.config['PHONE_NUMBER_ID']}/messages"
#     headers = {
#         "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
#         # "Content-Type": "application/json",  # opcional con json=...
#     }

#     logging.info("Enviando a Graph: url=%s to=%s body=%.60s",
#                  url, data.get("to"), data.get("text", {}).get("body", ""))

#     try:
#         resp = requests.post(url, json=data, headers=headers, timeout=15)
#         logging.info("Graph status=%s body=%s", resp.status_code, resp.text)
#         resp.raise_for_status()
#         return resp
#     except requests.Timeout:
#         logging.error("Timeout al enviar a Graph")
#         return jsonify({"status": "error", "message": "Request timed out"}), 408
#     except requests.RequestException as e:
#         logging.error("Error al enviar a Graph: %s", e)
#         # deja el cuerpo para entender el motivo
#         if e.response is not None:
#             logging.error("Graph resp=%s %s", e.response.status_code, e.response.text)
#         return jsonify({"status": "error", "message": "Failed to send message"}), 500

# def get_text_message_input(recipient, text):
#     return json.dumps(
#         {
#             "messaging_product": "whatsapp",
#             "recipient_type": "individual",
#             "to": recipient,
#             "type": "text",
#             "text": {"preview_url": False, "body": text},
#         }
#     )



def get_text_message_input(recipient, text):
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

# 2) send_message  (USAR json= Y LOGS CLAROS)
def send_message(data):
    headers = {
        "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
        # "Content-Type": "application/json",  # opcional con json=
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


#def generate_response(response):
    # Return text in uppercase
#    return response.upper()


# def send_message(data):
#     headers = {
#         "Content-type": "application/json",
#         "Authorization": f"Bearer {current_app.config['ACCESS_TOKEN']}",
#     }

#     url = f"https://graph.facebook.com/{current_app.config['VERSION']}/{current_app.config['PHONE_NUMBER_ID']}/messages"

#     try:
#         response = requests.post(
#             url, data=data, headers=headers, timeout=10
#         )  # 10 seconds timeout as an example
#         response.raise_for_status()  # Raises an HTTPError if the HTTP request returned an unsuccessful status code
#     except requests.Timeout:
#         logging.error("Timeout occurred while sending message")
#         return jsonify({"status": "error", "message": "Request timed out"}), 408
#     except (
#         requests.RequestException
#     ) as e:  # This will catch any general request exception
#         logging.error(f"Request failed due to: {e}")
#         return jsonify({"status": "error", "message": "Failed to send message"}), 500
#     else:
#         # Process the response as normal
#         log_http_response(response)
#         return response


def process_text_for_whatsapp(text):
    # Remove brackets
    pattern = r"\【.*?\】"
    # Substitute the pattern with an empty string
    text = re.sub(pattern, "", text).strip()

    # Pattern to find double asterisks including the word(s) in between
    pattern = r"\*\*(.*?)\*\*"

    # Replacement pattern with single asterisks
    replacement = r"*\1*"

    # Substitute occurrences of the pattern with the replacement
    whatsapp_style_text = re.sub(pattern, replacement, text)

    return whatsapp_style_text

# LE AGREGAMOS DOWN
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
    # wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
    # name = body["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"]

    # message = body["entry"][0]["changes"][0]["value"]["messages"][0]
    # message_body = message["text"]["body"]

    # TODO: implement custom function here
    #response = generate_response(message_body)

    # OpenAI Integration
    #response = generate_response(message_body, wa_id, name)
    #response = process_text_for_whatsapp(response)

    #data = get_text_message_input(current_app.config["RECIPIENT_WAID"], response)
    #send_message(data)
    


def is_valid_whatsapp_message(body):
    """
    Check if the incoming webhook event has a valid WhatsApp message structure.
    """
    return (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )

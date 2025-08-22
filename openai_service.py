from openai import OpenAI
import shelve                        
from dotenv import load_dotenv
import os
import time
import logging
from pathlib import Path
from .chat_store import (
    init_db, upsert_thread, touch_thread, insert_message, get_thread_rec
)
init_db()
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
client = OpenAI(api_key=OPENAI_API_KEY)

def get_thread_id_for_wa(wa_id: str) -> str | None: 
    rec = get_thread_rec(wa_id)
    if rec and rec["thread_id"]:
        return rec["thread_id"]
    shelve_path = str(BASE_DIR / "threads_db")
    try:
        with shelve.open(shelve_path) as sh:
            tid = sh.get(wa_id)
            if tid:
                upsert_thread(wa_id, tid)
                return tid
    except Exception:
        pass
    return None

def set_thread_id_for_wa(wa_id: str, thread_id: str) -> None:
    upsert_thread(wa_id, thread_id)
    shelve_path = str(BASE_DIR / "threads_db")
    try:
        with shelve.open(shelve_path, writeback=True) as sh:
            sh[wa_id] = thread_id
    except Exception:
        pass

ACTIVE_STATUSES = {"queued", "in_progress", "requires_action"}

def _wait_until_no_active_run(thread_id: str, timeout: int = 90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        runs = client.beta.threads.runs.list(thread_id=thread_id, order="desc", limit=1)
        if not runs.data:
            return
        status = runs.data[0].status
        if status not in ACTIVE_STATUSES:
            return
        time.sleep(0.7)
    raise TimeoutError("Run sigue activo demasiado tiempo")

def _wait_run_and_get_reply(thread_id: str, run_id: str, timeout: int = 120) -> str:
    t0 = time.time()
    last_status = None
    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        if run.status != last_status:
            logging.info("Run %s status=%s", run_id, run.status)
            last_status = run.status
        if run.status in ("completed", "failed", "cancelled", "expired"):
            break
        if run.status == "requires_action":
            logging.warning("Run requires_action (tool calls). Desactiva herramientas o implementa tool outputs.")
            break
        if time.time() - t0 > timeout:
            logging.error("Run timeout tras %ss; status=%s", int(time.time() - t0), run.status)
            return "(IA no disponible: timeout)"
        time.sleep(0.7)

    if run.status != "completed":
        err = getattr(run, "last_error", None)
        code = getattr(err, "code", None)
        message = getattr(err, "message", None)
        try:
            steps = client.beta.threads.runs.steps.list(thread_id=thread_id, run_id=run.id)
            steps_summary = [f"{s.type}:{getattr(s, 'status', '')}" for s in steps.data]
            logging.info("Run steps: %s", steps_summary)
        except Exception as e:
            logging.warning("No se pudieron obtener run steps: %s", e)
        logging.error("Run no completado. status=%s code=%s msg=%s", run.status, code, message)
        if run.status == "requires_action":
            return "(IA no disponible: requiere acción de herramienta. Desactiva herramientas o implementa tool outputs.)"
        if code == "invalid_model":
            return "(IA no disponible: modelo inválido/no habilitado en tu proyecto.)"
        if code == "insufficient_quota":
            return "(IA no disponible: cuota/billing insuficiente.)"
        return f"(IA no disponible: {run.status})"
    
    msgs = client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=20)
    for m in msgs.data:
        if m.role == "assistant":
            parts = []
            for p in m.content:
                if p.type == "text":
                    parts.append(p.text.value)
            text = "\n".join(parts).strip()
            if text:
                return text
    return "(Sin respuesta del assistant)"

def generate_response(message_body: str, wa_id: str, name: str = "") -> str:
    thread_id = get_thread_id_for_wa(wa_id) 
    if thread_id is None:
        logging.info(f"Creating new thread for {name} with wa_id {wa_id}")
        thread = client.beta.threads.create()
        thread_id = thread.id
        set_thread_id_for_wa(wa_id, thread_id)
    else:
        logging.info(f"Retrieving existing thread for {name} with wa_id {wa_id}")
        touch_thread(wa_id)
    insert_message(wa_id, thread_id, role="user", content=message_body) 
    try:
        client.beta.threads.messages.create(
            thread_id=thread_id, role="user", content=message_body
        )
    except Exception as e:
        msg = str(e)
        if "while a run" in msg:
            logging.info("Run activo, esperando y reintentando add message…")
            _wait_until_no_active_run(thread_id, timeout=90)
            client.beta.threads.messages.create(
                thread_id=thread_id, role="user", content=message_body
            )
        else:
            raise
    try:
        _wait_until_no_active_run(thread_id, timeout=90)     
    except TimeoutError:
        logging.warning("Timeout esperando run; Mantener mismo thread")  
    run = client.beta.threads.runs.create(
        thread_id=thread_id, assistant_id=OPENAI_ASSISTANT_ID
    )
    reply = _wait_run_and_get_reply(thread_id, run.id)
    if reply and isinstance(reply, str):
        insert_message(wa_id, thread_id, role="assistant", content=reply)
    touch_thread(wa_id)
    logging.info(f"Generated message: {reply[:120]}")
    return reply

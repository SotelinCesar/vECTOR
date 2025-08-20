from openai import OpenAI
import shelve
from dotenv import load_dotenv
import os
import time
import logging

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ASSISTANT_ID = os.getenv("OPENAI_ASSISTANT_ID")
client = OpenAI(api_key=OPENAI_API_KEY)


# def upload_file(path):
#     # Upload a file with an "assistants" purpose
#     file = client.files.create(
#         file=open("../../data/airbnb-faq.pdf", "rb"), purpose="assistants"
#     )


# def create_assistant(file):
#     """
#     You currently cannot set the temperature for Assistant via the API.
#     """
#     assistant = client.beta.assistants.create(
#         name="WhatsApp AirBnb Assistant",
#         instructions="You're a helpful WhatsApp assistant that can assist guests that are staying in our Paris AirBnb. Use your knowledge base to best respond to customer queries. If you don't know the answer, say simply that you cannot help with question and advice to contact the host directly. Be friendly and funny.",
#         tools=[{"type": "retrieval"}],
#         model="gpt-4-1106-preview",
#         file_ids=[file.id],
#     )
#     return assistant


# Use context manager to ensure the shelf file is closed properly
def check_if_thread_exists(wa_id):
    with shelve.open("threads_db") as threads_shelf:
        return threads_shelf.get(wa_id, None)


def store_thread(wa_id, thread_id):
    with shelve.open("threads_db", writeback=True) as threads_shelf:
        threads_shelf[wa_id] = thread_id

# DESDE ACA EL CAMBIO
ACTIVE_STATUSES = {"queued", "in_progress", "requires_action"}

def _wait_until_no_active_run(thread_id: str, timeout: int = 90):
    """Bloquea hasta que NO exista un run activo en el thread."""
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

# def _wait_run_and_get_reply(thread_id: str, run_id: str) -> str:
#     """Hace polling hasta completar y devuelve el último texto del assistant."""
#     while True:
#         run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
#         if run.status in ("completed", "failed", "cancelled", "expired"):
#             break
#         time.sleep(0.7)

#     if run.status != "completed":
#         return f"(IA no disponible: {run.status})"

#     msgs = client.beta.threads.messages.list(thread_id=thread_id, order="desc", limit=10)
#     for m in msgs.data:
#         if m.role == "assistant":
#             parts = [p.text.value for p in m.content if p.type == "text"]
#             return "\n".join(parts) if parts else "(Respuesta vacía)"
#     return "(Sin respuesta del assistant)"

def _wait_run_and_get_reply(thread_id: str, run_id: str, timeout: int = 120) -> str:
    """Hace polling hasta completar y devuelve el último texto del assistant.
    Loguea errores detallados si falla o requiere acción de herramientas.
    """
    t0 = time.time()
    last_status = None

    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)

        if run.status != last_status:
            logging.info("Run %s status=%s", run_id, run.status)
            last_status = run.status

        # Estados terminales
        if run.status in ("completed", "failed", "cancelled", "expired"):
            break

        # Si el assistant pide herramientas y no las manejas, corta con mensaje claro
        if run.status == "requires_action":
            logging.warning("Run requires_action (tool calls). Desactiva herramientas o implementa tool outputs.")
            break

        # Timeout defensivo
        if time.time() - t0 > timeout:
            logging.error("Run timeout tras %ss; status=%s", int(time.time() - t0), run.status)
            return "(IA no disponible: timeout)"

        time.sleep(0.7)

    if run.status != "completed":
        # Log detallado del fallo
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

        # Mensajes de ayuda específicos
        if run.status == "requires_action":
            return "(IA no disponible: requiere acción de herramienta. Desactiva herramientas o implementa tool outputs.)"
        if code == "invalid_model":
            return "(IA no disponible: modelo inválido/no habilitado en tu proyecto.)"
        if code == "insufficient_quota":
            return "(IA no disponible: cuota/billing insuficiente.)"

        return f"(IA no disponible: {run.status})"

    # Extrae el último texto del assistant
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
    # 1) thread por usuario
    thread_id = check_if_thread_exists(wa_id)
    if thread_id is None:
        logging.info(f"Creating new thread for {name} with wa_id {wa_id}")
        thread = client.beta.threads.create()
        store_thread(wa_id, thread.id)
        thread_id = thread.id
    else:
        logging.info(f"Retrieving existing thread for {name} with wa_id {wa_id}")

    # 2) espera a que no haya un run activo previo
    try:
        _wait_until_no_active_run(thread_id, timeout=90)
    except TimeoutError:
        logging.warning("Timeout esperando run; creando thread nuevo sin contexto")
        thread = client.beta.threads.create()
        store_thread(wa_id, thread.id)
        thread_id = thread.id

    # 3) añade mensaje del usuario (con retry si justo está activo)
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

    # 4) lanza run y devuelve respuesta
    run = client.beta.threads.runs.create(
        thread_id=thread_id, assistant_id=OPENAI_ASSISTANT_ID
    )
    reply = _wait_run_and_get_reply(thread_id, run.id)
    logging.info(f"Generated message: {reply[:120]}")
    return reply

# def run_assistant(thread, name):
#     # Retrieve the Assistant
#     assistant = client.beta.assistants.retrieve(OPENAI_ASSISTANT_ID)

#     # Run the assistant
#     run = client.beta.threads.runs.create(
#         thread_id=thread.id,
#         assistant_id=assistant.id,
#         # instructions=f"You are having a conversation with {name}",
#     )

#     # Wait for completion
#     # https://platform.openai.com/docs/assistants/how-it-works/runs-and-run-steps#:~:text=under%20failed_at.-,Polling%20for%20updates,-In%20order%20to
#     while run.status != "completed":
#         # Be nice to the API
#         time.sleep(0.5)
#         run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

#     # Retrieve the Messages
#     messages = client.beta.threads.messages.list(thread_id=thread.id)
#     new_message = messages.data[0].content[0].text.value
#     logging.info(f"Generated message: {new_message}")
#     return new_message


# def generate_response(message_body, wa_id, name):
#     # Check if there is already a thread_id for the wa_id
#     thread_id = check_if_thread_exists(wa_id)

#     # If a thread doesn't exist, create one and store it
#     if thread_id is None:
#         logging.info(f"Creating new thread for {name} with wa_id {wa_id}")
#         thread = client.beta.threads.create()
#         store_thread(wa_id, thread.id)
#         thread_id = thread.id

#     # Otherwise, retrieve the existing thread
#     else:
#         logging.info(f"Retrieving existing thread for {name} with wa_id {wa_id}")
#         thread = client.beta.threads.retrieve(thread_id)

#     # Add message to thread
#     message = client.beta.threads.messages.create(
#         thread_id=thread_id,
#         role="user",
#         content=message_body,
#     )

#     # Run the assistant and get the new message
#     new_message = run_assistant(thread, name)

#     return new_message

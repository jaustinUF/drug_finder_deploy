# 'pywebview' must be installed
import os
import threading
import asyncio
from queue import Queue
from typing import Dict, Optional

from nicegui import ui, app
from fastapi import Response        # loaded by nicegui

from backend import MCP_ChatBot, start_async_loop


vrsn = '1.1'
# pnt = True                      # print (response) if 'True'
pnt = False

# ---------------------------
# Shared backend engine
# ---------------------------
in_q: Queue = Queue()
out_q: Queue = Queue()

chatbot = MCP_ChatBot()
# Start backend async loop in worker thread
worker = threading.Thread(
    target=start_async_loop,
    args=(chatbot, in_q, out_q),
    daemon=True,
    name="AsyncWorker",
)
worker.start()

# ---------------------------
# Per-client timer registry
# ---------------------------
timers_by_client: Dict[str, Optional[ui.timer]] = {}

def _cancel_timer_for(client_id: str) -> None:
    t = timers_by_client.get(client_id)
    if t is not None:
        try:
            t.cancel()
        except Exception:
            pass
    timers_by_client[client_id] = None

def _on_disconnect(client):
    _cancel_timer_for(client.id)

app.on_disconnect(_on_disconnect)

# ---------------------------
# Healthcheck
# ---------------------------
@ui.page('/health')
def healthcheck():
    return Response(content='OK', media_type='text/plain')

# ---------------------------
# Small helpers: chat bubbles
# ---------------------------
def add_user_bubble(container: ui.column, text: str):
    """Right-aligned user bubble."""
    with container:
        with ui.row().classes('w-full justify-end'):
            with ui.card().classes('max-w-[80%] bg-blue-50 border border-blue-200 rounded-2xl p-3'):
                ui.label(text).classes('whitespace-pre-wrap text-gray-900')

def add_assistant_bubble(container: ui.column, text: str):
    """Left-aligned assistant bubble."""
    with container:
        with ui.row().classes('w-full justify-start'):
            with ui.card().classes('max-w-[80%] bg-gray-50 border border-gray-200 rounded-2xl p-3'):
                ui.label(text).classes('whitespace-pre-wrap text-gray-900')

# ---------------------------
# Main page (per-client UI)
# ---------------------------
@ui.page('/')
def index():
    is_paas = bool(os.environ.get('PORT'))
    client = ui.context.client

    # --- transcript storage: keep pairs chronological; render newest-first ---
    transcript = []          # list of dicts: {'q': str, 'a': Optional[str]}
    pending_pairs = []       # queue of pairs awaiting response (FIFO)

    with ui.column().classes('w-full max-w-4xl mx-auto'):
        # Header with live status
        with ui.row().classes('items-center gap-3'):
            ui.label('Drug Finder').classes('text-2xl font-bold')
            status_dot = ui.icon('circle').classes('text-gray-400')
            status_text = ui.label('Tools: —').classes('text-gray-600')

        # Description + sample questions
        ui.label(
            'I can help you with information about drugs and medications by searching RxNorm, a standardized drug nomenclature database.'
        ).classes('text-gray-600')
        ui.label('Here are some sample questions:').classes('text-gray-600')
        ui.markdown(
            '- I think the allergy med is Zertec—can you find likely matches and let me choose?\n'
            '- All I remember is ‘omep…’ for heartburn. Show 2–5 likely matches.\n'
            '- ibuprfen—what did I probably mean?\n'
            '- Is Panadol the same as acetaminophen in the US? Show the generic ingredient and branded equivalents.\n'
            '- I only know the brand Allegra—show the underlying ingredient and a couple of related products.'
        ).classes('text-gray-600')

        # Input box
        query_box = ui.input(
            label='Query',
            placeholder='Enter your query…'
        ).classes('w-full')

        # Ask button handler
        async def ask_query():
            q = (query_box.value or '').strip()
            if not q:
                return
            # Clear input; create a new pair (awaiting response)
            query_box.value = ''
            new_pair = {'q': q, 'a': None}
            transcript.append(new_pair)      # append chronologically
            pending_pairs.append(new_pair)   # mark as awaiting reply
            render_transcript()              # newest pair now shows at top (q only)
            spinner.visible = True

            # Send to backend queue
            in_q.put(q)

            # Wait for the assistant response (non-blocking)
            response = await asyncio.to_thread(out_q.get)
            # simple trap for rate error
            #   see https://chatgpt.com/c/68d020ba-81f8-8326-ac2d-c92130277d59 for professional solution
            if "Error code: 429" in response: response = "Sorry, I can't continue ... rate limit exceeded"
            #      *      *      *
            # Fill the oldest pending pair (FIFO) to keep Q/A aligned
            if pending_pairs:
                pending_pairs.pop(0)['a'] = response
            render_transcript()
            if pnt: print(response)
            spinner.visible = False

        ui.button(
            'Ask',
            on_click=ask_query
        ).classes('mt-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700')

        # spinner shown during backend processing
        spinner = ui.spinner(size='lg').props('color=blue').classes('mt-2')
        spinner.visible = False

        # Transcript area (scrollable)
        with ui.scroll_area().classes('w-full h-80 border rounded-lg p-3 bg-white mt-4'):
            chat_container = ui.column().classes('w-full gap-2')

        # --- helper: (re)render transcript with newest pair FIRST ---
        def render_transcript():
            chat_container.clear()
            for pair in reversed(transcript):
                add_user_bubble(chat_container, pair['q'])
                if pair.get('a') is not None:
                    add_assistant_bubble(chat_container, pair['a'])

        def clear_transcript():
            transcript.clear()
            pending_pairs.clear()
            chat_container.clear()
            spinner.visible = False

        # Quit button (local mode only)
        def shutdown_app():
            in_q.put("quit")
            try:
                _ = out_q.get(timeout=5)
            except Exception:
                pass
            app.shutdown()
            worker.join(timeout=2)

        # Footer buttons (bottom-right)
        with ui.row().classes('w-full justify-end gap-2 mt-4'):
            # Clear is safe to show on both PaaS and local
            ui.button(
                'Clear',
                on_click=clear_transcript
            ).classes('px-6 py-3 rounded-lg bg-gray-200 hover:bg-gray-300 text-black')

            # Only show Quit when not running on PaaS (preserving your logic & styling)
            if not is_paas:
                ui.button(
                    'Quit',
                    on_click=shutdown_app
                ).classes('px-6 py-3 bg-red-600 text-white rounded-lg hover:bg-red-700')

            ui.label('ver ' + vrsn).classes('text-gray-400')

        # ---------------------------
        # Status updater: show tool names
        # ---------------------------
        def update_status():
            tools = getattr(chatbot, 'available_tools', [])
            names = [t.get('name') for t in tools] if tools else []
            if names:
                status_dot.classes(replace='text-green-500')
                status_text.set_text('Tools: ' + ', '.join(names))
                _cancel_timer_for(client.id)
            else:
                status_dot.classes(replace='text-gray-400')
                status_text.set_text('Tools: —')

        timers_by_client[client.id] = ui.timer(0.5, update_status)

# ---------------------------
# Run mode: Railway vs local
# ---------------------------
if __name__ in {"__main__", "__mp_main__"}:
    port = os.environ.get("PORT")
    if port:
        print(f"Starting NiceGUI on 0.0.0.0:{port} (Railway)")
        # ui.run(host="0.0.0.0", port=int(port), reload=False)
        ui.run(host="0.0.0.0", port=int(port), reload=False, show=False) # see link below
    else:
        # ui.run(native=True, reload=False)
        ui.run(native=True, window_size=(800, 950), reload=False)
        # to handle 'pywebview' not installed: see https://chatgpt.com/c/68d41bcd-2460-832a-868b-efd657740d39

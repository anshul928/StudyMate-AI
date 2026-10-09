import io
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from urllib.request import urlopen
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from google import genai
from google.genai import types
from pypdf import PdfReader

load_dotenv()

MODEL_NAME = "gemini-3.5-flash-lite"

st.set_page_config(
    page_title="StudyMate AI",
    page_icon="🎓",
    layout="wide",
)


def get_api_key():
    """Read the key from Streamlit Secrets or the local .env file."""
    try:
        secret_key = st.secrets.get("GEMINI_API_KEY")
        if secret_key:
            return secret_key
    except Exception:
        pass
    return os.getenv("GEMINI_API_KEY")


def make_conversation(title="New chat", messages=None):
    """Create one conversation in the current browser session."""
    return {
        "id": uuid4().hex,
        "title": title,
        "messages": messages or [],
        "updated_at": datetime.now().timestamp(),
    }


@st.cache_resource(show_spinner=False)
def get_pdf_font_path():
    """Find a Hindi-capable font or download Noto Sans for cloud deployments."""
    font_paths = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Regular.ttf",
        r"C:\Windows\Fonts\Nirmala.ttc",
    ]
    local_font = next((path for path in font_paths if os.path.exists(path)), None)
    if local_font:
        return local_font

    cached_font = os.path.join(tempfile.gettempdir(), "StudyMate-NotoSansDevanagari.ttf")
    if os.path.exists(cached_font) and os.path.getsize(cached_font) > 10000:
        return cached_font

    font_url = (
        "https://raw.githubusercontent.com/notofonts/noto-fonts/main/"
        "hinted/ttf/NotoSansDevanagari/NotoSansDevanagari-Regular.ttf"
    )
    try:
        with urlopen(font_url, timeout=20) as response:
            font_data = response.read()
        if not font_data.startswith((b"\x00\x01\x00\x00", b"OTTO")):
            return None
        with open(cached_font, "wb") as font_file:
            font_file.write(font_data)
        return cached_font
    except Exception:
        return None


def make_answer_pdf(title, answer):
    """Create a PDF with Unicode support for Hindi and Hinglish answers."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    font_path = get_pdf_font_path()
    has_hindi = any("\u0900" <= char <= "\u097f" for char in answer)
    title = re.sub(r"[\U00010000-\U0010ffff\u200d\ufe0e\ufe0f]", "", title)
    answer = re.sub(r"[\U00010000-\U0010ffff\u200d\ufe0e\ufe0f]", "", answer)

    if font_path:
        if font_path.lower().endswith(".ttc"):
            pdf.add_font("StudyFont", fname=font_path, collection_font_number=0)
        else:
            pdf.add_font("StudyFont", fname=font_path)
        pdf.set_font("StudyFont", size=11)
        if has_hindi:
            pdf.set_text_shaping(True, script="deva", language="hin")
    else:
        if has_hindi:
            raise ValueError(
                "Hindi font download nahi ho paya. Internet connection check karke dobara try karo."
            )
        pdf.set_font("Helvetica", size=11)
        title = title.encode("latin-1", errors="replace").decode("latin-1")
        answer = answer.encode("latin-1", errors="replace").decode("latin-1")

    pdf.set_font_size(16)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(
        w=pdf.epw,
        h=10,
        text=title,
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(4)
    pdf.set_font_size(11)

    for line in answer.splitlines():
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(
            w=pdf.epw,
            h=7,
            text=line if line.strip() else " ",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    return bytes(pdf.output())


def wants_pdf_output(request_text):
    """Detect PDF creation requests, but leave requests about reading PDFs alone."""
    if not re.search(r"\bpdf\b", request_text, re.IGNORECASE):
        return False

    asks_to_create = bool(
        re.search(
            r"\b(?:bana\w*|bna\w*|kar\s*do|kr\s*do|create\w*|make\w*|"
            r"generate\w*|export\w*|download\w*|convert\w*|turn\w*|"
            r"want|need|chahiye|chahie|prepare\w*|print\w*|save\w*|"
            r"de\s+do|de\s+dena)\b",
            request_text,
            re.IGNORECASE,
        )
    )
    asks_about_an_input_pdf = bool(
        re.search(
            r"\b(?:summari[sz]e|summary|read|explain|extract|translate|analy[sz]e|review)\b",
            request_text,
            re.IGNORECASE,
        )
    )

    if asks_about_an_input_pdf and not asks_to_create:
        return False
    # If the student mentions a PDF without asking to read an existing one,
    # treat it as a request to make a downloadable PDF.
    return asks_to_create or not asks_about_an_input_pdf


def refuses_pdf_file_creation(answer):
    """Catch model replies that wrongly claim it cannot make or attach a PDF."""
    refusal = re.search(
        r"\b(?:cannot|can't|unable|not able|no puedo|nahi bana\w*|nahin bana\w*)\b"
        r".{0,100}\b(?:pdf|file|document|attach|download|create|generate|archivo|documento)\b"
        r"|\b(?:pdf|file|document)\b.{0,100}\b(?:cannot|can't|unable|not able|nahi|nahin)\b",
        answer,
        re.IGNORECASE | re.DOTALL,
    )
    return bool(refusal)


def pdf_title_from_request(request_text, fallback):
    """Turn a PDF request into a short, readable document title."""
    title = re.sub(
        r"\b(?:please|mujhe|mere|meri|iska|iski|liye|make|create|generate|export|download|convert|turn|this|it|into|as|a|an|the|pdf|bana|bna|banao|bnao|do|dijiye|ka|ki|ke|ko|par|pe|about|of|for|chahiye|chahie)\b",
        " ",
        request_text,
        flags=re.IGNORECASE,
    )
    title = re.sub(r"\s+", " ", title).strip(" -:,.!?\n")
    return title[:60] or fallback


def pdf_download_filename(title):
    """Create a safe, simple filename for a generated PDF."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    return f"{slug[:50] or 'studymate-study-notes'}.pdf"


def show_flashcards(answer):
    """Show generated flashcards with answers hidden in expanders."""
    pattern = re.compile(
        r"CARD\s*\d+\s*\nQUESTION:\s*(.*?)\nANSWER:\s*(.*?)(?=\nCARD\s*\d+\s*\n|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    cards = pattern.findall(answer)

    if not cards:
        st.markdown(answer)
        return

    for index, (question, card_answer) in enumerate(cards, start=1):
        with st.expander(f"🃏 Card {index}: {question.strip()}"):
            st.markdown(f"**Answer:** {card_answer.strip()}")


st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at 8% 0%, rgba(99, 102, 241, 0.20), transparent 30%),
            radial-gradient(circle at 95% 8%, rgba(20, 184, 166, 0.12), transparent 28%),
            #090f1d;
        color: #eef2ff;
    }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #10182a 0%, #0b1220 100%);
        border-right: 1px solid rgba(148, 163, 184, 0.14);
    }
    .block-container {
        max-width: 1160px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }
    .brand {
        font-size: 1.25rem;
        font-weight: 800;
        color: #f8fafc;
        margin-bottom: 0.2rem;
    }
    .hero {
        padding: 2rem;
        margin-bottom: 1.4rem;
        border: 1px solid rgba(165, 180, 252, 0.24);
        border-radius: 26px;
        background: linear-gradient(120deg, rgba(79, 70, 229, 0.27),
            rgba(15, 23, 42, 0.72) 58%, rgba(13, 148, 136, 0.16));
        box-shadow: 0 20px 60px rgba(0, 0, 0, 0.22);
    }
    .hero-kicker {
        color: #a5b4fc;
        font-size: 0.76rem;
        font-weight: 800;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        margin-bottom: 0.7rem;
    }
    .hero h1 {
        color: #f8fafc;
        font-size: clamp(2.1rem, 5vw, 3.4rem);
        line-height: 1.08;
        margin: 0;
        letter-spacing: -0.04em;
    }
    .hero h1 span { color: #a5b4fc; }
    .hero p {
        color: #cbd5e1;
        font-size: 1.05rem;
        margin: 1rem 0;
    }
    .hero-pill {
        display: inline-block;
        padding: 0.45rem 0.8rem;
        border: 1px solid rgba(165, 180, 252, 0.26);
        border-radius: 999px;
        color: #e0e7ff;
        background: rgba(15, 23, 42, 0.55);
        font-size: 0.85rem;
    }
    .mini-card {
        min-height: 105px;
        padding: 1rem;
        margin-bottom: 1.2rem;
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: 18px;
        background: rgba(15, 23, 42, 0.72);
    }
    .mini-card .icon { font-size: 1.35rem; }
    .mini-card strong {
        display: block;
        color: #f8fafc;
        margin: 0.35rem 0 0.2rem;
    }
    .mini-card small { color: #aab7cc; }
    .tool-banner {
        display: flex;
        align-items: center;
        gap: 1rem;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0 1rem;
        border: 1px solid rgba(45, 212, 191, 0.20);
        border-radius: 18px;
        background: rgba(13, 148, 136, 0.08);
    }
    .tool-icon { font-size: 2rem; }
    .tool-title { color: #f8fafc; font-size: 1.15rem; font-weight: 750; }
    .tool-tagline { color: #aab7cc; font-size: 0.9rem; margin-top: 0.15rem; }
    .stTextArea textarea {
        color: #f8fafc !important;
        background: rgba(10, 15, 29, 0.78) !important;
        border: 1px solid rgba(148, 163, 184, 0.24) !important;
        border-radius: 16px !important;
    }
    .stTextArea textarea:focus {
        border-color: #818cf8 !important;
        box-shadow: 0 0 0 1px #818cf8 !important;
    }
    div[data-baseweb="select"] > div {
        background: rgba(10, 15, 29, 0.78);
        border-color: rgba(148, 163, 184, 0.24);
        border-radius: 12px;
    }
    [data-testid="stFileUploaderDropzone"] {
        border: 1px dashed rgba(165, 180, 252, 0.4);
        border-radius: 16px;
        background: rgba(10, 15, 29, 0.45);
    }
    .stButton > button, [data-testid="stDownloadButton"] button {
        min-height: 3rem;
        color: white;
        font-weight: 750;
        border: 0;
        border-radius: 13px;
        background: linear-gradient(90deg, #6366f1, #8b5cf6);
        box-shadow: 0 8px 24px rgba(99, 102, 241, 0.24);
    }
    .stButton > button:hover, [data-testid="stDownloadButton"] button:hover {
        color: white;
        border: 0;
        box-shadow: 0 12px 30px rgba(99, 102, 241, 0.34);
    }
    /* Keep chat navigation compact and neutral, like a conversation list. */
    [data-testid="stSidebar"] div[data-testid="stButton"] > button {
        min-height: 2.45rem;
        justify-content: flex-start;
        text-align: left;
        padding: 0.45rem 0.7rem;
        color: #e5e7eb !important;
        border: 1px solid transparent !important;
        border-radius: 0.7rem !important;
        background: transparent !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button > div {
        width: 100%;
        justify-content: flex-start;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
        color: #f9fafb !important;
        border-color: transparent !important;
        background: #25262a !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {
        background: #303136 !important;
        color: #ffffff !important;
    }
    [data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]:hover {
        background: #3a3b40 !important;
    }
    [data-testid="stSidebar"] div[data-testid="stButton"] {
        margin-bottom: 0.1rem;
    }
    [data-testid="stChatInput"] textarea {
        color: #f8fafc !important;
        background: rgba(10, 15, 29, 0.92) !important;
    }
    [data-testid="stChatInput"] div[data-baseweb="textarea"] {
        border-color: rgba(148, 163, 184, 0.32) !important;
        border-radius: 18px !important;
    }
    @media (max-width: 640px) {
        .hero { padding: 1.35rem; }
        .hero p { font-size: 0.96rem; }
        .mini-card { min-height: 90px; padding: 0.75rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown('<div class="brand">🎓 StudyMate AI</div>', unsafe_allow_html=True)
st.sidebar.caption("Your personal study companion")
st.sidebar.markdown("---")

if "conversations" not in st.session_state:
    previous_messages = st.session_state.pop("chat_history", [])
    first_question = next(
        (item.get("text", "") for item in previous_messages if item.get("role") == "user"),
        "",
    )
    previous_title = " ".join(first_question.split())[:36] or "New chat"
    st.session_state.conversations = [
        make_conversation(previous_title, previous_messages)
    ]
    st.session_state.active_chat_id = st.session_state.conversations[0]["id"]

if st.sidebar.button("✎  New chat", use_container_width=True, key="new_chat"):
    new_conversation = make_conversation()
    st.session_state.conversations.append(new_conversation)
    st.session_state.active_chat_id = new_conversation["id"]
    st.session_state.chat_input = ""

st.sidebar.markdown("#### Projects")
st.sidebar.caption("No projects")
st.sidebar.markdown("#### Recents")
recent_conversations = sorted(
    [chat for chat in st.session_state.conversations if chat["messages"]],
    key=lambda item: item["updated_at"],
    reverse=True,
)
for conversation in recent_conversations:
    title = conversation["title"]
    if len(title) > 30:
        title = title[:29].rstrip() + "…"
    button_type = (
        "primary"
        if conversation["id"] == st.session_state.active_chat_id
        else "secondary"
    )
    if st.sidebar.button(
        f"💬 {title}",
        key=f"recent_chat_{conversation['id']}",
        type=button_type,
        use_container_width=True,
    ):
        st.session_state.active_chat_id = conversation["id"]
        st.session_state.chat_input = ""

active_chat = next(
    conversation
    for conversation in st.session_state.conversations
    if conversation["id"] == st.session_state.active_chat_id
)
st.sidebar.markdown("---")

tools = {
    "Study Chat": {
        "icon": "💬",
        "tagline": "Ask follow-up questions without losing the conversation.",
        "task": "Answer the student's latest message as a helpful tutor. Use the conversation history for follow-up questions. If the new question is unrelated, answer it on its own.",
    },
    "Note Summarizer": {
        "icon": "📝",
        "tagline": "Turn long notes into clear key points.",
        "task": "Summarize the notes as short, clear bullet points. Focus on the main ideas and do not repeat the full input.",
    },
    "Quiz Generator": {
        "icon": "🧠",
        "tagline": "Create practice questions from your notes.",
        "task": "Create 5 multiple-choice questions from the material. Give 4 options for each question and an answer key at the end.",
    },
    "Answer Improver": {
        "icon": "✍️",
        "tagline": "Make a written answer clearer and stronger.",
        "task": "Improve the answer's clarity, grammar, and accuracy while keeping its meaning. Show the improved answer and briefly mention the main improvements.",
    },
    "Concept Explainer": {
        "icon": "💡",
        "tagline": "Understand a difficult topic in simple language.",
        "task": "Explain the topic in simple student-friendly language. Include one easy example and define difficult words.",
    },
    "Maths/Science Step-by-Step": {
        "icon": "🔬",
        "tagline": "See how to solve a problem, one step at a time.",
        "task": "Solve the Maths or Science problem step by step. Explain why each step is needed, show the final answer, and check it if possible.",
    },
    "Flashcards": {
        "icon": "🃏",
        "tagline": "Revise with questions and hidden answers.",
        "task": "Create 8 flashcards from the study material. Use exactly this format for every card:\nCARD 1\nQUESTION: question text\nANSWER: answer text\nThen CARD 2, and continue.",
    },
    "Study Planner": {
        "icon": "🗓️",
        "tagline": "Make a study schedule for your exam.",
        "task": "Create a realistic day-by-day study plan from the topics provided. Include short breaks, revision time, and a small practice task each day.",
    },
}

feature = st.sidebar.selectbox("Choose a study tool", list(tools.keys()))
language = st.sidebar.selectbox(
    "Answer language", ["Hinglish", "Hindi", "English", "Same as my input"]
)
level = st.sidebar.selectbox("Explanation level", ["Very easy", "Normal", "Detailed"])
st.sidebar.markdown("---")

st.markdown(
    """
    <div class="hero">
        <div class="hero-kicker">Study better, every day</div>
        <h1>Your study sidekick<br><span>for every subject.</span></h1>
        <p>Turn notes into clarity, practice, and confidence.</p>
        <div class="hero-pill">✨ Gemini-powered study support</div>
    </div>
    """,
    unsafe_allow_html=True,
)

card1, card2, card3 = st.columns(3)
for column, icon, title, description in [
    (card1, "📖", "Learn clearly", "Make tricky topics easier to understand."),
    (card2, "⚡", "Revise faster", "Turn long notes into useful study points."),
    (card3, "🎯", "Practice more", "Build confidence with quizzes and answers."),
]:
    with column:
        st.markdown(
            f"""
            <div class="mini-card">
                <div class="icon">{icon}</div>
                <strong>{title}</strong>
                <small>{description}</small>
            </div>
            """,
            unsafe_allow_html=True,
        )

selected_tool = tools[feature]
st.markdown(
    f"""
    <div class="tool-banner">
        <div class="tool-icon">{selected_tool['icon']}</div>
        <div>
            <div class="tool-title">{feature}</div>
            <div class="tool-tagline">{selected_tool['tagline']}</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

exam_date = None
study_hours = None
if feature == "Study Planner":
    st.markdown("#### 📅 Exam details")
    date_col, hours_col = st.columns(2)
    with date_col:
        exam_date = st.date_input(
            "Exam date", value=date.today() + timedelta(days=14), min_value=date.today()
        )
    with hours_col:
        study_hours = st.number_input(
            "Study hours per day", min_value=1, max_value=12, value=2, step=1
        )

submitted_message = st.chat_input(
    "Ask StudyMate AI...",
    key="chat_input",
    accept_audio=True,
    accept_file=True,
    file_type=["pdf"],
)
text = ""
pdf_text = ""
uploaded_pdf = None
voice_submission_ok = True

if submitted_message is not None:
    if isinstance(submitted_message, str):
        text = submitted_message
        submitted_audio = None
        submitted_files = []
    else:
        text = submitted_message.text or ""
        submitted_audio = submitted_message.audio
        submitted_files = submitted_message.files

    if submitted_files:
        uploaded_pdf = submitted_files[0]
        try:
            reader = PdfReader(io.BytesIO(uploaded_pdf.getvalue()))
            pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
            if pdf_text:
                if len(pdf_text) > 40000:
                    pdf_text = pdf_text[:40000]
                    st.info("PDF ka pehla hissa liya gaya hai, taaki request chhoti rahe.")
            else:
                st.warning("Is PDF se text nahi mila. Text wala PDF try karo.")
        except Exception:
            st.error("PDF read nahi ho paayi. Koi doosri PDF try karo.")

    if submitted_audio is not None:
        api_key = get_api_key()
        if not api_key:
            st.error("Gemini API key nahi mili. Apni .env file check karo.")
            voice_submission_ok = False
        else:
            try:
                with st.spinner("Voice ko text mein badal raha hoon..."):
                    client = genai.Client(api_key=api_key)
                    transcript = client.models.generate_content(
                        model=MODEL_NAME,
                        contents=[
                            "Transcribe the speech exactly in the language spoken. "
                            "Return only the words that were spoken; do not answer or summarize.",
                            types.Part.from_bytes(
                                data=submitted_audio.getvalue(),
                                mime_type=submitted_audio.type or "audio/wav",
                            ),
                        ],
                    )
                if transcript.text and transcript.text.strip():
                    text = "\n".join(
                        part for part in (text.strip(), transcript.text.strip()) if part
                    )
                else:
                    st.error("Voice samajh nahi aayi. Mic se dobara bolo.")
                    voice_submission_ok = False
            except Exception:
                st.error("Voice process nahi hui. Mic se dobara try karo.")
                voice_submission_ok = False

if submitted_message is not None and voice_submission_ok:
    content = text.strip()
    if pdf_text:
        content = f"{content}\n\nPDF notes:\n{pdf_text}".strip()

    if not content:
        st.warning("Pehle sawaal likho, mic se bolo, ya PDF attach karo.")
    else:
        api_key = get_api_key()
        if not api_key:
            st.error("Gemini API key nahi mili. Apni .env file check karo.")
        else:
            language_rules = {
                "Same as my input": (
                    "Reply in the same language as the student's input. If it is written "
                    "in Roman Hindi or Hinglish, reply in simple Roman Hinglish."
                ),
                "Hindi": "Reply in simple Hindi.",
                "English": "Reply in simple English.",
                "Hinglish": "Reply in simple Hinglish using Roman letters.",
            }
            planner_details = ""
            if feature == "Study Planner" and exam_date:
                days_left = max(1, (exam_date - date.today()).days)
                planner_details = (
                    f"\nExam date: {exam_date.strftime('%d %B %Y')}"
                    f"\nDays available: {days_left}"
                    f"\nStudy time per day: {study_hours} hours"
                )

            pdf_requested = wants_pdf_output(text)
            pdf_title = pdf_title_from_request(text, feature)
            if pdf_requested:
                task_instruction = (
                    "Create a complete, helpful document about the subject the student "
                    "requested. Include a clear title and useful sections. The app will "
                    "turn your text into a downloadable PDF, so return the document text "
                    "only; do not say you cannot create, attach, or download a PDF."
                )
                source_instruction = (
                    "Use any notes the student provided. If no notes were provided, use "
                    "your general knowledge to write the requested document; do not refuse "
                    "or ask for notes just because the material is empty."
                )
            else:
                task_instruction = selected_tool["task"]
                source_instruction = (
                    "Use the student's material as the source. If information is missing, "
                    "say so clearly instead of guessing."
                )

            prompt = f"""
You are StudyMate AI, a patient and helpful study assistant.
{source_instruction}
Use the conversation history to understand follow-up questions. Focus on the
student's latest message and answer it directly. Do not repeat earlier answers
unless the student asks for a recap.

Feature: {feature}
Task: {task_instruction}
Language: {language_rules[language]} Follow exactly; do not switch languages unexpectedly.
Explanation level: {level}
{planner_details}

Student's material:
{content}
"""
            should_refresh = False
            try:
                with st.spinner("StudyMate-AI Loading..."):
                    client = genai.Client(api_key=api_key)
                    history = []
                    for message in active_chat["messages"]:
                        if message["role"] == "user":
                            history.append(
                                types.Content(
                                    role="user",
                                    parts=[types.Part.from_text(text=message["prompt"])],
                                )
                            )
                        else:
                            history.append(
                                types.Content(
                                    role="model",
                                    parts=[types.Part.from_text(text=message["text"])],
                                )
                            )

                    chat = client.chats.create(model=MODEL_NAME, history=history)
                    response = chat.send_message(prompt)
                    if pdf_requested and (
                        not response.text or refuses_pdf_file_creation(response.text)
                    ):
                        recent_context = "\n".join(
                            f"{('Student' if item['role'] == 'user' else 'StudyMate')}: {item['text']}"
                            for item in active_chat["messages"][-6:]
                        )
                        retry_prompt = f"""
Write the complete contents for the student's requested PDF document.
The app itself creates and downloads the PDF, so do not discuss file-creation limits
and do not refuse just because you cannot attach a file. Use the provided context
when the student says "this" or refers to an earlier answer. If no notes were given,
use general knowledge. Write the actual document with a title and useful sections.

Language: {language_rules[language]}
Student's latest request: {text}
Recent conversation context:
{recent_context}
"""
                        response = client.models.generate_content(
                            model=MODEL_NAME,
                            contents=retry_prompt,
                        )
                if response.text:
                    shown_question = text.strip()
                    if uploaded_pdf:
                        pdf_label = f"\n\n📎 PDF notes: {uploaded_pdf.name}"
                        shown_question = f"{shown_question}{pdf_label}".strip()
                    if not active_chat["messages"]:
                        title_source = text.strip() or (
                            uploaded_pdf.name if uploaded_pdf else "Study chat"
                        )
                        active_chat["title"] = " ".join(title_source.split())[:36]
                    active_chat["messages"].append(
                        {
                            "role": "user",
                            "text": shown_question or "📎 PDF notes",
                            "prompt": prompt,
                            "feature": feature,
                        }
                    )
                    active_chat["messages"].append(
                        {
                            "role": "assistant",
                            "text": response.text,
                            "feature": feature,
                            "pdf_requested": pdf_requested,
                            "pdf_title": pdf_title,
                        }
                    )
                    active_chat["updated_at"] = datetime.now().timestamp()
                    should_refresh = True
                else:
                    st.warning("Answer nahi mila. Dobara try karo.")
            except Exception as error:
                error_message = str(error).lower()
                if "429" in error_message or "resource_exhausted" in error_message:
                    st.error("Free quota abhi use ho chuki hai. Baad mein try karo.")
                elif "api_key" in error_message or "401" in error_message:
                    st.error("API key check nahi ho paayi. .env file check karo.")
                else:
                    st.error(f"Answer nahi mila. Error type: {type(error).__name__}")
            if should_refresh:
                st.rerun()

if active_chat["messages"]:
    st.markdown("---")
    st.subheader(f"💬 {active_chat['title']}")

    for message_index, message in enumerate(active_chat["messages"]):
        role = "user" if message["role"] == "user" else "assistant"
        with st.chat_message(role):
            if role == "user":
                st.markdown(message["text"])
            elif message.get("feature") == "Flashcards":
                show_flashcards(message["text"])
            else:
                st.markdown(message["text"])
            if role == "assistant" and message.get("pdf_requested"):
                try:
                    requested_pdf = make_answer_pdf(
                        f"StudyMate AI - {message.get('pdf_title', 'Study material')}",
                        message["text"],
                    )
                    st.download_button(
                        "📄 Download your requested PDF",
                        data=requested_pdf,
                        file_name=pdf_download_filename(
                            message.get("pdf_title", "StudyMate study material")
                        ),
                        mime="application/pdf",
                        key=f"requested_pdf_{active_chat['id']}_{message_index}",
                    )
                except Exception as error:
                    st.error("PDF nahi ban payi. Jawab chat mein available hai.")
                    st.caption(f"Reason: {type(error).__name__}: {error}")


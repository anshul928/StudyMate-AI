import os
import re
from datetime import date, timedelta

import streamlit as st
from dotenv import load_dotenv
from google import genai
from pypdf import PdfReader

load_dotenv()

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
        question = question.strip()
        card_answer = card_answer.strip()

        with st.expander(f"🃏 Card {index}: {question}"):
            st.markdown(f"**Answer:** {card_answer}")


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

    [data-testid="stHeader"] {
        background: transparent;
    }

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
        background:
            linear-gradient(120deg, rgba(79, 70, 229, 0.27),
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

    .hero h1 span {
        color: #a5b4fc;
    }

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

    .mini-card .icon {
        font-size: 1.35rem;
    }

    .mini-card strong {
        display: block;
        color: #f8fafc;
        margin: 0.35rem 0 0.2rem;
    }

    .mini-card small {
        color: #aab7cc;
    }

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

    .tool-icon {
        font-size: 2rem;
    }

    .tool-title {
        color: #f8fafc;
        font-size: 1.15rem;
        font-weight: 750;
    }

    .tool-tagline {
        color: #aab7cc;
        font-size: 0.9rem;
        margin-top: 0.15rem;
    }

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

    .stButton > button {
        min-height: 3rem;
        color: white;
        font-weight: 750;
        border: 0;
        border-radius: 13px;
        background: linear-gradient(90deg, #6366f1, #8b5cf6);
        box-shadow: 0 8px 24px rgba(99, 102, 241, 0.24);
    }

    .stButton > button:hover {
        color: white;
        border: 0;
        box-shadow: 0 12px 30px rgba(99, 102, 241, 0.34);
    }

    @media (max-width: 640px) {
        .hero {
            padding: 1.35rem;
        }

        .hero p {
            font-size: 0.96rem;
        }

        .mini-card {
            min-height: 90px;
            padding: 0.75rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.sidebar.markdown(
    '<div class="brand">🎓 StudyMate AI</div>',
    unsafe_allow_html=True,
)
st.sidebar.caption("Your personal study companion")
st.sidebar.markdown("---")

tools = {
    "Note Summarizer": {
        "icon": "📝",
        "tagline": "Turn long notes into clear key points.",
        "task": (
            "Summarize the notes as short, clear bullet points. "
            "Focus on the main ideas and do not repeat the full input."
        ),
    },
    "Quiz Generator": {
        "icon": "🧠",
        "tagline": "Create practice questions from your notes.",
        "task": (
            "Create 5 multiple-choice questions from the material. "
            "Give 4 options for each question and an answer key at the end."
        ),
    },
    "Answer Improver": {
        "icon": "✍️",
        "tagline": "Make a written answer clearer and stronger.",
        "task": (
            "Improve the answer's clarity, grammar, and accuracy while "
            "keeping its meaning. Show the improved answer and briefly "
            "mention the main improvements."
        ),
    },
    "Concept Explainer": {
        "icon": "💡",
        "tagline": "Understand a difficult topic in simple language.",
        "task": (
            "Explain the topic in simple student-friendly language. "
            "Include one easy example and define difficult words."
        ),
    },
    "Maths/Science Step-by-Step": {
        "icon": "🔬",
        "tagline": "See how to solve a problem, one step at a time.",
        "task": (
            "Solve the Maths or Science problem step by step. Explain why "
            "each step is needed, show the final answer, and check it if possible."
        ),
    },
    "Flashcards": {
        "icon": "🃏",
        "tagline": "Revise with questions and hidden answers.",
        "task": (
            "Create 8 flashcards from the study material. Use exactly this "
            "format for every card:\nCARD 1\nQUESTION: question text\n"
            "ANSWER: answer text\nThen CARD 2, and continue."
        ),
    },
    "Study Planner": {
        "icon": "🗓️",
        "tagline": "Make a study schedule for your exam.",
        "task": (
            "Create a realistic day-by-day study plan from the topics provided. "
            "Include short breaks, revision time, and a small practice task each day."
        ),
    },
}

feature = st.sidebar.selectbox("Choose a study tool", list(tools.keys()))

language = st.sidebar.selectbox(
    "Answer language",
    ["Same as my input", "Hindi", "English", "Hinglish"],
)

level = st.sidebar.selectbox(
    "Explanation level",
    ["Very easy", "Normal", "Detailed"],
)

st.sidebar.markdown("---")
st.sidebar.warning("Private details mat daalo; free-tier prompts Google ko bheje jaate hain.")

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

with card1:
    st.markdown(
        """
        <div class="mini-card">
            <div class="icon">📖</div>
            <strong>Learn clearly</strong>
            <small>Make tricky topics easier to understand.</small>
        </div>
        """,
        unsafe_allow_html=True,
    )

with card2:
    st.markdown(
        """
        <div class="mini-card">
            <div class="icon">⚡</div>
            <strong>Revise faster</strong>
            <small>Turn long notes into useful study points.</small>
        </div>
        """,
        unsafe_allow_html=True,
    )

with card3:
    st.markdown(
        """
        <div class="mini-card">
            <div class="icon">🎯</div>
            <strong>Practice more</strong>
            <small>Build confidence with quizzes and answers.</small>
        </div>
        """,
        unsafe_allow_html=True,
    )

selected_tool = tools[feature]

st.markdown(
    f"""
    <div class="tool-banner">
        <div class="tool-icon">{selected_tool["icon"]}</div>
        <div>
            <div class="tool-title">{feature}</div>
            <div class="tool-tagline">{selected_tool["tagline"]}</div>
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
            "Exam date",
            value=date.today() + timedelta(days=14),
            min_value=date.today(),
        )

    with hours_col:
        study_hours = st.number_input(
            "Study hours per day",
            min_value=1,
            max_value=12,
            value=2,
            step=1,
        )

uploaded_pdf = st.file_uploader(
    "📄 Add class notes as a PDF (optional)",
    type=["pdf"],
)

pdf_text = ""

if uploaded_pdf:
    try:
        reader = PdfReader(uploaded_pdf)
        pdf_text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        ).strip()

        if pdf_text:
            st.success(f"PDF ready: {len(reader.pages)} pages.")
            if len(pdf_text) > 40000:
                pdf_text = pdf_text[:40000]
                st.info("PDF ka pehla hissa liya gaya hai, taaki request chhoti rahe.")
        else:
            st.warning(
                "Is PDF se text nahi mila. Agar PDF scanned image hai, "
                "to notes ko text box mein paste karo."
            )
    except Exception:
        st.error("PDF read nahi ho paayi. Koi doosri PDF try karo.")

text = st.text_area(
    "📝 Your notes, question, answer, or topics",
    height=190,
    placeholder="Yahan apna content likho ya paste karo...",
)

if st.button("✨ Generate study help", type="primary", use_container_width=True):
    content = text.strip()

    if pdf_text:
        content = f"{content}\n\nPDF notes:\n{pdf_text}".strip()

    if not content:
        st.warning("Pehle text likho ya text wali PDF add karo.")
    else:
        api_key = get_api_key()

        if not api_key:
            st.error("Gemini API key nahi mili. Apni .env file check karo.")
        else:
            language_rules = {
                "Same as my input": "Reply in the same language as the student's input.",
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

            prompt = f"""
You are StudyMate AI, a patient and helpful study assistant.
Use the student's material as the source. If information is missing,
say so clearly instead of guessing.

Feature: {feature}
Task: {selected_tool["task"]}
Language: {language_rules[language]}
Explanation level: {level}
{planner_details}

Student's material:
{content}
"""

            try:
                with st.spinner("Gemini tumhare liye study help bana raha hai..."):
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model="gemini-3.5-flash-lite",
                        contents=prompt,
                    )

                if response.text:
                    st.markdown("---")
                    st.subheader("✨ Your study help")

                    if feature == "Flashcards":
                        show_flashcards(response.text)
                    else:
                        st.markdown(response.text)

                    st.caption("Important answers ko apne class notes se verify kar lena.")
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
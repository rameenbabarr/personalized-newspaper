"""Meen, the newspaper assistant in the web pages' chat box.

A small LangGraph loop (agent -> tools -> agent) over an OpenRouter model. Chat
memory lives in an in-memory checkpointer keyed by the browser tab's thread id,
so it lasts until the server restarts. The system prompt is rebuilt every turn
from what the page shows and user.md, and is never stored, so it
cannot go stale in memory.
"""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from src.config import USER_MD_PATH, iso_date, load_paper, load_user_md
from src.log import close, error, ok, start_run
from src.taste import db, trends

MODEL = "z-ai/glm-5.3-flash"
OPENROUTER_URL = "https://openrouter.ai/api/v1"
GENERATE = "generate_newspaper"
# One paper at a time: two browser tabs must not run the newsroom twice.
_generating = threading.Lock()

SYSTEM = """You are Meen, the newspaper assistant for {paper}, a private morning paper made for one reader: Rameen.
Today is {today} (Asia/Karachi).

Personality: warm, quick and a little sassy. Keep replies short: a few sentences unless asked for more.
Formatting: light Markdown: **bold**, *italics*, [links](url). Vary the shape to fit the answer. Bullets are for things that are genuinely a list; a two-line answer, a comparison or an opinion is prose, so do not turn every reply into bullets.
Numbers always go in a table, never in a bulleted list of figures. The moment you are about to write two or more counts, tallies or percentages, set them exactly like this instead:

| Topic | Votes |
| --- | --- |
| Space | 3 |
| Palestine | 3 |

Two or three columns, each figure in its own column, a line of prose before or after it. This applies to votes by topic, likes against dislikes, counts per week, anything counted. No headings or code blocks.
Answer the question that was asked and nothing wider. Asked which topics they voted down, list only the topics with a down vote, not a tally of everything; asked about one topic, answer about that one. A table of every figure you happen to hold is not an answer.

Talking about the reader: everything you know about their taste is in "The reader's interests" below. Call it their interests, or what you know about them. Never mention files, file names, formats, configs or "profile", and never say what is missing from a file. If something isn't in their interests, just say you don't know it yet and ask.

What you can do:
- Talk about the stories on screen, the reader's interests, their taste history and anything else they bring up.
- {generate}: print a fresh edition for today. It takes about a minute. Call it when the reader asks for a paper or clearly wants one. It needs no arguments, and the page reloads to show the new edition afterwards.
- edit_interests: change the reader's interests. The newsroom reads them every morning, so a change there changes tomorrow's paper. Before editing, say in one line what you will change, unless the reader has already told you exactly what to do. Keep the existing style: short plain sentences under "## Topic" headings.
- read_edition: the stories in any printed edition. The section below shows only the page the reader is on, so when they ask what is in the paper and that page is not an edition, call this instead of saying you cannot see it. No date means the most recent edition.
- taste_report: the per-topic tally of stories printed, liked and disliked, plus themes rising and fading and the trial topics. Use it before you make claims about the reader's taste, and call it again rather than reusing an earlier answer in this conversation: they vote as they read, so the numbers move under you.

Never invent stories, sources or votes. Never say you cannot see something before you have tried the tool that would fetch it. Offer to print a paper when there is genuinely no edition to read.

## What the reader is looking at right now
The reader may change pages between messages; earlier replies described what was on screen then.
{page}

## The reader's interests
{interests}
"""


@tool(GENERATE)
def generate_newspaper() -> str:
    """Print a fresh edition of today's newspaper (gathers news, writes, renders the PDF). Takes about a minute."""
    if not _generating.acquire(blocking=False):
        return "A paper is already being printed. Tell the reader to hang on."
    # The CLI's own run function, without opening Preview: the reader is in the browser.
    from src.cli import generate_edition

    start_run("meen-preview")
    try:
        edition = generate_edition(open_pdf=False)
        ok("meen: edition ready")
        heads = [f"- [{a.role}] {a.headline}" for a in edition.articles]
        return f"Printed the {edition.date} edition with {len(heads)} stories:\n" + "\n".join(heads)
    except Exception as exc:
        error(f"meen generate failed: {exc}")
        return f"The print run failed: {exc}"
    finally:
        close()
        _generating.release()


@tool
def edit_interests(find: str, replace: str) -> str:
    """Edit the reader's interests. `find` must be exact text that appears once in them and is replaced by `replace`.
    Pass an empty `find` to append `replace` at the end (e.g. a new "## Topic" section)."""
    text = load_user_md(USER_MD_PATH)
    if not find:
        updated = text.rstrip("\n") + "\n\n" + replace.strip("\n") + "\n"
    else:
        count = text.count(find)
        if count == 0:
            return "No change: `find` is not in the interests. Copy the text exactly."
        if count > 1:
            return f"No change: `find` appears {count} times. Include more surrounding text."
        updated = text.replace(find, replace, 1)
    USER_MD_PATH.write_text(updated)
    return "Interests updated."


@tool
def read_edition(date: str = "") -> str:
    """The stories in one printed edition, as previews. `date` is YYYY-MM-DD; leave it
    empty for the most recent edition. Use this whenever the reader asks about a paper
    that is not the one on screen."""
    from src.web.app import edition_dates, page_snapshot

    days = edition_dates()
    if not days:
        return "No edition has been printed yet. Offer to print one."
    day = date.strip() or days[0]
    if day not in days:
        return f"No edition for {day}. Printed so far: {', '.join(days[:10])}."
    return page_snapshot(f"/day/{day}")


@tool
def taste_report() -> str:
    """The reader's taste history: vote counts, top themes, rising and fading themes, recent likes and dislikes, discovery topics."""
    from src.web.app import topic_labels

    stories = db.stories_with_votes()
    summary = trends.summarize(stories, topics=db.topics())
    summary.pop("weeks", None)  # per-week tables are chart data; too long to be useful here
    # The per-topic tally lived only inside "weeks", so without this the model
    # had to guess at "which topics did I vote down" from recent headlines.
    labels = topic_labels()
    summary["topics"] = [
        {**row, "label": labels.get(row["topic"], row["topic"])} for row in trends.topic_tally(stories)
    ]
    report = db.latest_report()
    if report:
        summary["weekly_report"] = report
    return json.dumps(summary, indent=1, default=str)


TOOLS = [generate_newspaper, edit_interests, read_edition, taste_report]


def _paper_name() -> str:
    try:
        return load_paper().get("paper_name") or "The Rameen Times"
    except Exception:
        return "The Rameen Times"


def system_prompt(page: str) -> str:
    return SYSTEM.format(
        paper=_paper_name(),
        today=iso_date(),
        generate=GENERATE,
        page=page or "Nothing is being shown.",
        interests=load_user_md(USER_MD_PATH).strip(),
    )


def _model():
    from langchain_openai import ChatOpenAI

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return ChatOpenAI(
        model=os.environ.get("MEEN_MODEL", MODEL),
        api_key=key,
        base_url=OPENROUTER_URL,
        temperature=0.6,
        timeout=60,
    ).bind_tools(TOOLS)


def build_graph(model=None):
    """model: anything with .invoke(messages) -> AIMessage; tests pass a fake."""
    llm = model

    def agent(state: MessagesState, config: RunnableConfig) -> dict:
        nonlocal llm
        llm = llm or _model()
        page = config.get("configurable", {}).get("page", "")
        reply = llm.invoke([SystemMessage(system_prompt(page)), *state["messages"]])
        return {"messages": [reply]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=MemorySaver())


@lru_cache(maxsize=1)
def graph():
    return build_graph()


def _text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, list):  # some providers return content blocks
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return (content or "").strip()


def chat(thread_id: str, message: str, page: str, app=None) -> Iterator[dict]:
    """One reader turn. Yields {"type": "generating"} when a print run starts,
    then {"type": "reply", "text": ..., "reload": bool}."""
    app = app or graph()
    config = {"configurable": {"thread_id": thread_id, "page": page}, "recursion_limit": 12}
    printed = False
    last: AIMessage | None = None
    for update in app.stream({"messages": [HumanMessage(message)]}, config, stream_mode="updates"):
        for node, delta in update.items():
            for msg in (delta or {}).get("messages", []):
                if node == "agent" and isinstance(msg, AIMessage):
                    last = msg
                    if any(c["name"] == GENERATE for c in msg.tool_calls):
                        yield {"type": "generating"}
                elif node == "tools" and msg.name == GENERATE and msg.content.startswith("Printed"):
                    printed = True
    text = _text(last) if last else ""
    yield {"type": "reply", "text": text or "Hmm, I lost my train of thought. Say that again?", "reload": printed}


def history(thread_id: str, app=None) -> list[dict]:
    """The visible transcript for a thread: reader lines and Meen's text replies."""
    app = app or graph()
    state = app.get_state({"configurable": {"thread_id": thread_id}})
    out: list[dict] = []
    for msg in (state.values or {}).get("messages", []):
        if isinstance(msg, HumanMessage):
            out.append({"role": "user", "text": msg.content})
        elif isinstance(msg, AIMessage) and _text(msg):
            out.append({"role": "meen", "text": _text(msg)})
    return out

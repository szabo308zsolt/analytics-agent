import re, json, sqlite3, os
from dataclasses import dataclass, field
from typing import Protocol

from dotenv import load_dotenv
load_dotenv()  # reads OPENAI_API_KEY (and any other keys) from the .env file

from decisions import analytics_decision



class LLM(Protocol):
    """Any class with this method can power the agent."""
    def complete(self, system: str, messages: list[dict]) -> str:
        """Return the model's reply to `messages` as plain text."""


class OpenAICompatibleLLM:
    """Default provider. Also works for any OpenAI-compatible server, such as Ollama."""
    def __init__(self, model, base_url=None, api_key=None, temperature=0.0):
        from openai import OpenAI
        self.client = OpenAI(base_url=base_url,
                             api_key=api_key or os.getenv("OPENAI_API_KEY", "not-needed"))
        self.model, self.temperature = model, temperature

    def complete(self, system, messages):
        r = self.client.chat.completions.create(
            model=self.model, temperature=self.temperature,
            messages=[{"role": "system", "content": system}] + messages)
        return r.choices[0].message.content


#     ## test
# cl = OpenAICompatibleLLM(model="gpt-5.4-mini-2026-03-17")
# cl.complete("a", [{"role": "user", "content": "What is the capital of Hungary"}]
#             )


def get_schema(conn: sqlite3.Connection, sample_rows: int = 3) -> str:
    out = []
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tables:
        ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0]
        out.append(ddl + ";")
        if sample_rows:
            cur = conn.execute(f'SELECT * FROM "{t}" LIMIT {sample_rows}')
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if rows:
                out.append(f"/* sample rows from {t}: columns {cols}")
                out += [f"   {r}" for r in rows]
                out.append("*/")
    return "\n".join(out)


SYSTEM_PROMPT = """You are an expert {dialect} analyst. Convert the user's question into ONE SQL query.

Rules:
- Use only the tables and columns in the schema below. Never invent columns.
- Read-only: a single SELECT (CTEs with WITH are fine). No INSERT/UPDATE/DELETE/DDL.
- Qualify ambiguous columns with table aliases.
- Add LIMIT {max_rows} unless the question asks for an aggregate that returns few rows.
- If the question cannot be answered from the schema, reply exactly: CANNOT_ANSWER: <reason>
- Return the SQL inside a ```sql code block and nothing else.

Schema:
{schema}
"""


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    sql = (m.group(1) if m else text).strip()
    return sql.rstrip(";").strip()


FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|truncate|attach|detach|"
    r"pragma|vacuum|grant|revoke)\b", re.I)


def validate_sql(sql: str) -> None:
    stripped = re.sub(r"'(?:[^']|'')*'", "''", sql)          # ignore string literals
    stripped = re.sub(r"--.*?$|/\*.*?\*/", "", stripped, flags=re.S | re.M)
    if ";" in stripped:
        raise ValueError("Only a single statement is allowed.")
    if not re.match(r"^\s*(select|with)\b", stripped, re.I):
        raise ValueError("Only SELECT queries are allowed.")
    if FORBIDDEN.search(stripped):
        raise ValueError("Query contains a forbidden keyword.")


@dataclass
class AgentResult:
    question: str
    sql: str | None = None
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    answer: str = ""
    attempts: int = 0
    error: str | None = None


class TextToSQLAgent:
    def __init__(self, llm: LLM, db_path: str, dialect="SQLite", max_rows=100, max_retries=3):
        self.llm, self.dialect, self.max_rows, self.max_retries = llm, dialect, max_rows, max_retries
        # read-only connection: the database itself refuses writes
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.schema = get_schema(self.conn)

    def _system(self):
        return SYSTEM_PROMPT.format(dialect=self.dialect, schema=self.schema,
                                    max_rows=self.max_rows)

    def ask(self, question: str) -> AgentResult:
        res = AgentResult(question)
        messages = [{"role": "user", "content": question}]
        for attempt in range(1, self.max_retries + 1):
            res.attempts = attempt
            reply = self.llm.complete(self._system(), messages)
            if reply.strip().startswith("CANNOT_ANSWER"):
                res.error, res.answer = reply.strip(), reply.split(":", 1)[-1].strip()
                return res
            sql = extract_sql(reply)
            try:
                validate_sql(sql)
                cur = self.conn.execute(sql)
                res.sql = sql
                res.columns = [d[0] for d in cur.description]
                res.rows = cur.fetchmany(self.max_rows)
                res.error = None
                break
            except Exception as e:                       # feed the error back and retry
                res.sql, res.error = sql, f"{type(e).__name__}: {e}"
                messages += [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": f"That query failed with:\n{res.error}\n"
                     "Fix it and return only the corrected SQL in a ```sql block."}]
        if res.error is None:
            res.answer = self._summarize(res)
        return res

    def _summarize(self, res: AgentResult) -> str:
        """Turn the result rows into a short plain-English answer."""
        preview = json.dumps({"columns": res.columns, "rows": res.rows[:20]}, default=str)
        return self.llm.complete(
            "You answer questions from SQL results. Be concise and use exact numbers. "
            "Do not invent data not present in the result.",
            [{"role": "user", "content":
              f"Question: {res.question}\nSQL: {res.sql}\nResult: {preview}"}])



DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "gpt-5.4-mini-2026-03-17")


def build_llm(provider: str = DEFAULT_PROVIDER, model: str | None = None) -> LLM:
    """OpenAI is the default. Other providers are imported only when asked for."""
    if provider == "openai":
        return OpenAICompatibleLLM(model or DEFAULT_MODEL)
    if provider == "ollama":  # local models via Ollama's OpenAI-compatible endpoint
        return OpenAICompatibleLLM(model or "llama3.1",
                                   base_url="http://localhost:11434/v1", api_key="ollama")
    if not model:
        raise ValueError(f"--model is required for provider '{provider}'")
    if provider == "anthropic":
        from providers import AnthropicLLM   # needs: uv add anthropic
        return AnthropicLLM(model)
    if provider == "gemini":
        from providers import GeminiLLM      # needs: uv add google-genai
        return GeminiLLM(model)
    raise ValueError(f"Unknown provider '{provider}'")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="shop.db")
    p.add_argument("--provider", default=DEFAULT_PROVIDER,
                   choices=["openai", "ollama", "anthropic", "gemini"])
    p.add_argument("--model", default=None, help=f"default for openai: {DEFAULT_MODEL}")
    a = p.parse_args()
    agent = TextToSQLAgent(build_llm(a.provider, a.model), a.db)
    while True:
        q = input("\nAsk> ").strip()
        if q in {"", "exit", "quit"}:
            break
        is_analytics = analytics_decision(q)
        if not(analytics_decision(q)):
            print("Not an analytics question")
            continue
        r = agent.ask(q)
        print(f"\nSQL ({r.attempts} attempt(s)):\n{r.sql}")
        if r.error:
            print("Error:", r.error)
        else:
            print(r.columns)
            for row in r.rows[:10]:
                print(row)
            print("\nAnswer:", r.answer)

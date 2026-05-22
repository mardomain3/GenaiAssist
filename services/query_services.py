from dotenv import load_dotenv
import os
import ssl
import httpx
import json
import re
import pandas as pd
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_groq import ChatGroq

load_dotenv()

ssl._create_default_https_context = ssl._create_unverified_context
http_client = httpx.Client(verify=False)

llm = ChatGroq(
    groq_api_key=os.getenv("GROQ_API_KEY"),
    model_name="llama-3.3-70b-versatile",
    temperature=0,
    http_client=http_client
)

query_prompt = PromptTemplate(
    input_variables=["columns", "question"],
    template="""
You are a pandas expert.
The dataframe is named df and has these columns:
{columns}

Convert the user's question into ONLY a valid pandas expression that returns DATA.

Strict Rules:
1. Use df as the dataframe name
2. Return ONLY the pandas expression, nothing else
3. Do NOT use .plot(), matplotlib, seaborn, or any visualization library
4. Do NOT use print()
5. Do NOT use markdown or code fences
6. Do NOT import anything
7. The expression must return a DataFrame, Series, scalar, or string
8. For counts/frequency use: df['col'].value_counts()
9. For groupby use: df.groupby('col')['num_col'].sum()
10. For trends over time: df.groupby('date_col')['num_col'].sum()
11. Never chain .plot() at the end — just return the data

User Question: {question}
"""
)

insight_prompt = PromptTemplate(
    input_variables=["question", "result"],
    template="""
You are a business data analyst.
The user asked: {question}
The query returned this result:
{result}
Give a short, clear business insight (3-5 sentences) based on this data.
Focus on what this means for the business.
"""
)

chart_prompt = PromptTemplate(
    input_variables=["question", "result", "columns"],
    template="""
You are a data visualization expert. You must respond with ONLY a JSON object, no other text.

The user asked: {question}
Result preview: {result}
Available columns: {columns}

Return ONLY this JSON with no extra text, no explanation, no markdown:
{{"chart_type": "bar", "x_column": "col1", "y_column": "col2", "title": "Chart Title", "reason": "why"}}

Chart type rules:
- "bar" for comparisons, rankings, counts
- "line" for trends, time series, payment trends
- "pie" for proportions under 8 categories
- "scatter" for correlations
- "none" for single values or text

x_column must be one of: {columns}
y_column must be one of: {columns}
"""
)

query_chain = query_prompt | llm | StrOutputParser()
insight_chain = insight_prompt | llm | StrOutputParser()
chart_chain = chart_prompt | llm | StrOutputParser()


def extract_json(text: str) -> dict:
    """Robustly extract JSON from LLM response even if it has extra text."""
    # Clean markdown fences
    text = text.replace("```json", "").replace("```", "").strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try to find JSON object using regex
    match = re.search(r'\{.*?\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    # If all fails return none chart
    print(f"Could not parse chart JSON from: {text}")
    return {"chart_type": "none"}


def detect_chart(question: str, display_result, result_columns: list) -> dict:
    """Detect best chart type with fallback logic."""

    # Keyword-based fallback — if LLM fails, use this
    question_lower = question.lower()
    fallback = {"chart_type": "none"}

    if any(w in question_lower for w in ["trend", "over time", "monthly", "daily", "weekly", "yearly", "line"]):
        if len(result_columns) >= 2:
            fallback = {
                "chart_type": "line",
                "x_column": result_columns[0],
                "y_column": result_columns[1],
                "title": "Trend Over Time",
                "reason": "Line chart for time-based trend"
            }
    elif any(w in question_lower for w in ["distribution", "proportion", "percentage", "share", "pie"]):
        if len(result_columns) >= 2:
            fallback = {
                "chart_type": "pie",
                "x_column": result_columns[0],
                "y_column": result_columns[1],
                "title": "Distribution",
                "reason": "Pie chart for proportions"
            }
    elif any(w in question_lower for w in ["top", "most", "count", "sum", "total", "compare", "bar"]):
        if len(result_columns) >= 2:
            fallback = {
                "chart_type": "bar",
                "x_column": result_columns[0],
                "y_column": result_columns[1],
                "title": "Comparison",
                "reason": "Bar chart for comparison"
            }

    if not result_columns or len(result_columns) < 2:
        return {"chart_type": "none"}

    try:
        chart_raw = chart_chain.invoke({
            "question": question,
            "result": str(display_result)[:500],  # limit size to avoid token issues
            "columns": result_columns
        }).strip()

        result = extract_json(chart_raw)

        # Validate columns exist in result
        if result.get("chart_type") != "none":
            x_col = result.get("x_column")
            y_col = result.get("y_column")
            if x_col not in result_columns or y_col not in result_columns:
                print(f"Invalid columns in chart config: {x_col}, {y_col}")
                return fallback

        return result

    except Exception as e:
        print(f"Chart detection failed: {e}, using fallback")
        return fallback


def run_query(file_path: str, question: str):
    if file_path.endswith(".xlsx"):
         df = pd.read_excel(file_path)
    elif file_path.endswith(".csv"):
         df=pd.read_csv(file_path)

    # Step 1: Generate pandas query
    pandas_query = query_chain.invoke({
        "columns": list(df.columns),
        "question": question
    }).strip()

    # Step 2: Block any plot/visualization calls
    blocked_keywords = ['.plot(', 'matplotlib', 'seaborn', 'plt.', 'sns.', 'pyplot']
    for kw in blocked_keywords:
        if kw in pandas_query:
            pandas_query = pandas_query.split('.plot(')[0].strip()

    # Step 3: Execute query
    try:
        result = eval(pandas_query)

        if isinstance(result, pd.DataFrame):
            display_result = result.head(20)
            result_dict = display_result.to_dict(orient="records")
            result_columns = list(display_result.columns)

        elif isinstance(result, pd.Series):
            display_result = result.head(20)
            df_result = display_result.reset_index()
            df_result.columns = [str(c) for c in df_result.columns]
            result_dict = df_result.to_dict(orient="records")
            result_columns = list(df_result.columns)

        else:
            display_result = result
            result_dict = None
            result_columns = []

        # Step 4: Insight
        insight = insight_chain.invoke({
            "question": question,
            "result": str(display_result)
        })

        # Step 5: Chart config with robust detection
        chart_config = {"chart_type": "none"}
        if result_dict and len(result_dict) > 0:
            chart_config = detect_chart(question, display_result, result_columns)

        return {
            "success": True,
            "pandas_query": pandas_query,
            "result": str(display_result),
            "result_data": result_dict,
            "result_columns": result_columns,
            "insight": insight,
            "chart_config": chart_config
        }

    except Exception as e:
        return {
            "success": False,
            "pandas_query": pandas_query,
            "error": str(e)
        }


def get_columns(file_path: str):
    df = pd.read_excel(file_path)
    return list(df.columns)
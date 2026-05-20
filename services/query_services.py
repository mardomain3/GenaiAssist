from dotenv import load_dotenv
import os
import ssl
import httpx
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
Convert the user's question into ONLY a valid pandas query expression.
Rules:
1. Use df as the dataframe name
2. Return ONLY the pandas code, nothing else
3. Do not explain anything
4. Do not use markdown or code fences
5. Do not use print() — just the expression
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

# NEW: chart detection prompt
chart_prompt = PromptTemplate(
    input_variables=["question", "result", "columns"],
    template="""
You are a data visualization expert.
The user asked: {question}
The result data is:
{result}
The columns available are: {columns}

Decide the BEST chart type for this data and return ONLY a JSON object like this:
{{
  "chart_type": "bar" | "line" | "pie" | "scatter" | "none",
  "x_column": "column name for x axis or null",
  "y_column": "column name for y axis or null",
  "title": "chart title",
  "reason": "why this chart type"
}}

Rules:
- Use "bar" for comparisons, rankings, counts
- Use "line" for trends over time
- Use "pie" for proportions/percentages (max 8 slices)
- Use "scatter" for correlations between two numbers
- Use "none" if data is a single value or text only
- Return ONLY the JSON, no explanation, no markdown
"""
)

query_chain = query_prompt | llm | StrOutputParser()
insight_chain = insight_prompt | llm | StrOutputParser()
chart_chain = chart_prompt | llm | StrOutputParser()

def run_query(file_path: str, question: str):
    df = pd.read_excel(file_path)

    # Step 1: Generate pandas query
    pandas_query = query_chain.invoke({
        "columns": list(df.columns),
        "question": question
    }).strip()

    # Step 2: Execute query
    try:
        result = eval(pandas_query)

        if isinstance(result, pd.DataFrame):
            display_result = result.head(20)
            result_dict = display_result.to_dict(orient="records")
            result_columns = list(display_result.columns)
        elif isinstance(result, pd.Series):
            display_result = result.head(20)
            result_dict = display_result.reset_index().to_dict(orient="records")
            result_columns = list(display_result.reset_index().columns)
        else:
            display_result = result
            result_dict = None
            result_columns = []

        # Step 3: Generate insight
        insight = insight_chain.invoke({
            "question": question,
            "result": str(display_result)
        })

        # Step 4: Detect best chart type
        chart_config = None
        if result_dict:
            try:
                import json
                chart_raw = chart_chain.invoke({
                    "question": question,
                    "result": str(display_result),
                    "columns": result_columns
                }).strip()
                # Clean any markdown fences just in case
                chart_raw = chart_raw.replace("```json", "").replace("```", "").strip()
                chart_config = json.loads(chart_raw)
            except Exception as e:
                print(f"Chart detection failed: {e}")
                chart_config = {"chart_type": "none"}

        return {
            "success": True,
            "pandas_query": pandas_query,
            "result": str(display_result),
            "result_data": result_dict,         # structured data for chart
            "result_columns": result_columns,
            "insight": insight,
            "chart_config": chart_config        # chart instructions
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
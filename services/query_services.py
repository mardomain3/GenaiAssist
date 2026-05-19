from dotenv import load_dotenv
import os
import pandas as pd
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_google_genai import ChatGoogleGenerativeAI


# CONFIGURE LANGCHAIN + GEMINI

load_dotenv()
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    temperature=0
)
 

# PROMPT 1: NATURAL LANGUAGE → PANDAS QUERY


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


# PROMPT 2: RESULT → BUSINESS INSIGHT


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


# BUILD CHAINS


query_chain = query_prompt | llm | StrOutputParser()
insight_chain = insight_prompt | llm | StrOutputParser()


# MAIN FUNCTION


def run_query(file_path: str, question: str):

    # Load dataset
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
        else:
            display_result = result

        # Step 3: Generate insight
        insight = insight_chain.invoke({
            "question": question,
            "result": str(display_result)
        })

        return {
            "success": True,
            "pandas_query": pandas_query,
            "result": str(display_result),
            "insight": insight
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
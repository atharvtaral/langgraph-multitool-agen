import os
import requests
import streamlit as st
from dotenv import load_dotenv
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.checkpoint.memory import MemorySaver 
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, AIMessage
from tavily import TavilyClient
import wikipedia
from bs4 import BeautifulSoup
import base64

# Load environment variables from .env file
load_dotenv()

# Securely set API keys and configuration constants
os.environ["GROQ_API_KEY"] = os.getenv("GROQ_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
BASE_URL = "https://api.openweathermap.org/data/2.5/weather"


# ==========================================
# 🛠️ AGENT TOOLS DEFINITION
# ==========================================
@tool
def internet_search(query: str) -> str:
    """Use this tool to search the internet for live, current, or real-time information."""
    client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    response = client.search(query=query, max_results=2)
    results = [res["content"] for res in response.get("results", [])]
    return "\n\n".join(results) if results else "No results found."


# --- Tool 2: Weather Forecast Tool (OpenWeatherMap) ---
@tool
def get_weather(city: str) -> str:
    """Return current weather forecast for a city using OpenWeather API.
    Use this whenever the user asks about the weather, temperature, or climate of a specific city"""
    params = {
        'q': city,
        'appid': OPENWEATHER_API_KEY,
        'units': 'metric'
    }
    try:
        response = requests.get(BASE_URL, params=params,timeout=10)

        if response.status_code != 200:
            return f"Error: Unable to find city '{city}' or API issue (Status {response.status_code})."
        
        result = response.json()
        location = result["name"]
        # Fixed typo: 'discription' changed to 'description'
        description = result["weather"][0]["description"].capitalize()
        temp = result["main"]["temp"]

        return f"Weather in {location}: {description}, Temperature: {temp}C."
    
    except Exception as e:
        return f"Network Error while fetching weather: {str(e)}."


# --- Tool 3: Wikipedia Summary Fetcher ---
@tool
def fetch_wikipedia_summary(query: str) -> str:
    """
    Use this tool to get a concise summary from wikipedia about concepts, historical events, famous people, or technical terms.
    Input should be a specific topic name (e.g., 'Artificial Intelligence', 'Albert Einstein)
    """
    try:
        wikipedia.set_lang("en")
        summary = wikipedia.summary(query, sentences=3)
        return f"Wikipedia Summary for '{query}' \n{summary}"

    except wikipedia.exceptions.DisambiguationError as e:
        return f"Too vague. Multiple topics found for '{query}'. Please be more specific. Options: {e.options[:3]}"
    except wikipedia.exceptions.PageError:
        # Triggered if the topic does not exist on Wikipedia
        return f"Could not find any Wikipedia page for '{query}'."
    except Exception as e:
        return f"An error occurred while fetching Wikipedia: {str(e)}"


# --- Tool 4: Website Scraper and Summarizer ---
@tool
def scrape_website_content(url: str) -> str:
    """
    Use this tool to extract text content from any website or blog URL. 
    Use it whenever the user shares a link/URL and asks to summarize it, explain it, or extract information from it.
    """
    try:
        # Send an HTTP request with a mock browser header to avoid blockades
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return f"Failed to fetch website. Status code: {response.status_code}"
            
        # Parse the HTML content using BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove script and style elements to strip out unneeded code clutter
        for script in soup(["script", "style"]):
            script.extract()
            
        text = soup.get_text()
        
        # Clean up excess whitespaces and blank newlines
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = '\n'.join(chunk for chunk in chunks if chunk)
        
        # Return only the first 4000 characters to keep payload within model token boundaries
        return clean_text[:4000]
        
    except Exception as e:
        return f"An error occurred while scraping the URL: {str(e)}"

# ==========================================
# ⛓️ LANGGRAPH COMPILATION (Cached for Streamlit)
# ==========================================
@st.cache_resource
def init_langgraph_agent():
    tools = [internet_search,get_weather,fetch_wikipedia_summary,scrape_website_content]
    llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.4).bind_tools(tools)

    def call_llm(state: MessagesState):
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    # Define and assemble the LangGraph workflow structure
    graph_builder = StateGraph(MessagesState)
    graph_builder.add_node("agent", call_llm)
    graph_builder.add_node("tools", ToolNode(tools))

    graph_builder.add_edge(START, "agent")
    graph_builder.add_conditional_edges("agent", tools_condition)
    graph_builder.add_edge("tools", "agent")

    # Enable persistent conversation state tracking using memory checkpointer
    memory = MemorySaver()
    return graph_builder.compile(checkpointer=memory)

graph = init_langgraph_agent()
config = {"configurable": {"thread_id": "streamlit_chat_session"}}

# ==========================================
# 🎨 STREAMLIT UI RENDER
# ==========================================

# या एकाच ब्लॉकContainer मुळे टायटल आणि सबटायटल पूर्ण बॅनर्सच्या उभ्या (Up-Down) आणि आडव्या (Left-Right) सेंटरमध्ये येतील
st.markdown(
    """
    <div style='display: flex; flex-direction: column; justify-content: center; align-items: center; height: 320px; text-align: center;'>
        <h1 style='color: #ffffff; font-size: 3.2rem; font-weight: 800; margin: 0px; padding: 0px; text-shadow: 2px 2px 8px rgba(0,0,0,0.7); line-height: 1.2;'>
            🤖 Agentic Multi-Tool AI Engine
        </h1>
        <p style='color: #ffffff; opacity: 0.9; font-size: 1.5rem; font-weight: 500; margin-top: 15px; margin-bottom: 0px; text-shadow: 1px 1px 4px rgba(0,0,0,0.5);'>
            Powered by LangGraph & Llama-3.3-70b-Versatile on Groq
        </p>
    </div>
    """, 
    unsafe_allow_html=True
)

# Initialize conversation tracking in Streamlit session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render chat history from session state
for msg in st.session_state.messages:
    with st.chat_message("user" if isinstance(msg, HumanMessage) else "assistant"):
        st.markdown(msg.content)

# Accept real-time user chat inputs
if user_input := st.chat_input("Ask me anything (e.g., Weather, Web Search, Wiki, Summarize Link)..."):
    
    # Render user prompt immediately on the web layout
    with st.chat_message("user"):
        st.markdown(user_input)
    
    # Save the input to state
    new_user_msg = HumanMessage(content=user_input)
    st.session_state.messages.append(new_user_msg)
    
    # Process graph response inside a clean loader status bar
    with st.chat_message("assistant"):
        with st.spinner("Thinking & Executing Tools..."):
            try:
                output = graph.invoke(
                    {"messages": st.session_state.messages}, 
                    config=config
                )
                ai_response = output["messages"][-1].content
                st.markdown(ai_response)
                
                # Append finalized AI text back to history
                st.session_state.messages.append(AIMessage(content=ai_response))
            except Exception as e:
                st.error(f"Something went wrong: {e}")


def apply_custom_theme(image_file):
    if os.path.exists(image_file):
        with open(image_file, "rb") as f:
            encoded_string = base64.b64encode(f.read()).decode()
    else:
        return
    
    st.markdown(
        f"""
        <style>
        /* 1. FORCE BACKGROUND ON EVERY CONCEIVABLE LAYER */
        html, body, .stApp, 
        div[data-testid="stAppViewContainer"], 
        div[data-testid="stHeader"],
        div[data-testid="stMain"],
        .stMainBlockContainer,
        div[data-testid="stVerticalBlock"] {{
            background-image: url(data:image/png;base64,{encoded_string}) !important;
            background-size: cover !important;
            background-position: center !important;
            background-repeat: no-repeat !important;
            background-attachment: fixed !important;
            background-color: transparent !important;
        }}
        
        /* 2. COMPLETELY DESTROY THE WHITE BOTTOM WRAPPER */
        div[data-testid="stBottom"],
        div[data-testid="stBottomBlockContainer"],
        .stBottomBlockContainer,
        footer,
        div[data-testid="stDecoration"] {{
            background-color: transparent !important;
            background-image: none !important;
            border: none !important;
            box-shadow: none !important;
        }}
        
        /* Remove the white background overlay that Streamlit adds under content */
        .stMainBlockContainer {{
            background-color: transparent !important;
            padding-top: 3rem !important;
        }}

        /* 3. TEXT COLORS - CRISP WHITE */
        h1, h2, h3, p, span, label, .stMarkdown, p style, [data-testid="stMarkdownContainer"] p {{
            color: #ffffff !important;
        }}
        
        /* 4. CHAT BUBBLES - GLASSMORPHISM */
        div[data-testid="stChatMessage"] {{
            background-color: rgba(255, 255, 255, 0.12) !important;
            border-radius: 12px !important;
            border: 1px solid rgba(255, 255, 255, 0.2) !important;
            backdrop-filter: blur(5px) !important;
        }}
        
        div[data-testid="stChatMessage"] p {{
            color: #ffffff !important;
        }}

        /* 5. SOLID ROUNDED WHITE CHAT INPUT */
        div[data-testid="stChatInput"] {{
            background-color: #ffffff !important;
            border-radius: 25px !important;
            padding: 6px 12px !important;
            box-shadow: 0px 4px 20px rgba(0,0,0,0.6) !important;
            border: 1px solid #ffffff !important;
        }}
        
        div[data-testid="stChatInput"] textarea {{
            color: #111111 !important;
            -webkit-text-fill-color: #111111 !important;
            background-color: transparent !important;
        }}
        
        div[data-testid="stChatInput"] textarea::placeholder {{
            color: #555555 !important;
            -webkit-text-fill-color: #555555 !important;
        }}
        
        div[data-testid="stChatInput"] button {{
            background-color: #111111 !important;
            color: #ffffff !important;
            border-radius: 50% !important;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )
apply_custom_theme('bg.jpg')

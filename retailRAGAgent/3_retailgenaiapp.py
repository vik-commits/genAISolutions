import streamlit as st
import os
import csv
from pathlib import Path
from datetime import datetime
import requests
import json
from typing import List, Tuple, Optional
import hashlib
from functools import lru_cache
import time

# Configuration
RETAIL_ANALYSIS_FOLDER = "retail_analysis_output"
GENAI_OUTPUT_FOLDER = "genaioutput"
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_HEALTH_URL = "http://localhost:11434/api/tags"
MODEL_NAME = "mistral"

# OPTIMIZED TIMEOUTS
REQUEST_TIMEOUT = 120  # Reduced from 500s - most queries should finish in 2 mins
STREAM_RESPONSE = True  # Enable streaming for faster perceived response
MAX_CONTEXT_SIZE = 8000  # Limit context to prevent timeout (chars)
MAX_LINES_PER_CSV = 100  # Limit CSV rows to prevent bloated context

# Cache settings
CACHE_EXPIRY = 3600  # 1 hour cache for embeddings/queries
EMBEDDING_CACHE = {}

# Create directories
Path(RETAIL_ANALYSIS_FOLDER).mkdir(exist_ok=True)
Path(GENAI_OUTPUT_FOLDER).mkdir(exist_ok=True)

@st.cache_resource
def get_cache():
    """Streamlit cache for expensive operations."""
    return {"queries": {}, "csv_hash": None}

def get_file_hash(csv_files: dict) -> str:
    """Get hash of CSV files to detect changes."""
    content = json.dumps({k: len(v) for k, v in csv_files.items()}, sort_keys=True)
    return hashlib.md5(content.encode()).hexdigest()

def load_csv_files(limit_rows: bool = True) -> dict:
    """Load CSV files with optional row limiting for performance."""
    csv_data = {}
    
    if not os.path.exists(RETAIL_ANALYSIS_FOLDER):
        return csv_data
    
    for file in os.listdir(RETAIL_ANALYSIS_FOLDER):
        if file.endswith('.csv'):
            file_path = os.path.join(RETAIL_ANALYSIS_FOLDER, file)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    
                    # Limit rows to prevent massive context
                    if limit_rows and len(lines) > MAX_LINES_PER_CSV:
                        limited_lines = lines[:1] + lines[1:MAX_LINES_PER_CSV]
                        csv_data[file] = ''.join(limited_lines) + f"\n... ({len(lines) - MAX_LINES_PER_CSV} more rows)"
                    else:
                        csv_data[file] = f.read()
            except Exception as e:
                st.error(f"Error reading {file}: {str(e)}")
    
    return csv_data

def build_context(csv_files: dict, max_size: int = MAX_CONTEXT_SIZE) -> str:
    """Build context with size limits to prevent timeouts."""
    context = "Available retail analysis data:\n\n"
    
    for filename, content in csv_files.items():
        file_section = f"File: {filename}\n---\n{content}\n\n"
        
        # Stop adding if context gets too large
        if len(context) + len(file_section) > max_size:
            context += f"\n[Context truncated - {len(csv_files) - list(csv_files.keys()).index(filename)} more files available]"
            break
        
        context += file_section
    
    return context

def check_ollama_health() -> Tuple[bool, str]:
    """Check Ollama availability."""
    try:
        response = requests.get(OLLAMA_HEALTH_URL, timeout=5)
        if response.status_code == 200:
            models = response.json().get('models', [])
            model_names = [m.get('name', '') for m in models]
            
            if any(MODEL_NAME in name for name in model_names):
                return True, f"Ollama running with {MODEL_NAME}"
            else:
                return False, f"Model '{MODEL_NAME}' not found"
        else:
            return False, "Ollama health check failed"
    except requests.exceptions.ConnectionError:
        return False, "Cannot connect to Ollama on localhost:11434"
    except Exception as e:
        return False, f"Health check error: {str(e)}"

def query_ollama_streaming(prompt: str, context: str):
    """Query Ollama with streaming for faster perceived response."""
    try:
        full_prompt = f"""You are a retail analysis assistant.

Use the following retail analysis data to answer the user's question:

{context}

User Question: {prompt}

Provide a detailed response based on the data. If no relevant info exists, respond with: 'No suitable response found error'"""
        
        response = requests.post(
            OLLAMA_API_URL,
            json={
                "model": MODEL_NAME,
                "prompt": full_prompt,
                "stream": True,  # Enable streaming
                "temperature": 0.7,
            },
            timeout=REQUEST_TIMEOUT,
            stream=True
        )
        
        if response.status_code == 200:
            full_response = ""
            for line in response.iter_lines():
                if line:
                    try:
                        json_obj = json.loads(line)
                        if 'response' in json_obj:
                            full_response += json_obj['response']
                            yield full_response
                    except json.JSONDecodeError:
                        continue
            return full_response
        else:
            return f"Error: {response.status_code}"
    
    except requests.exceptions.Timeout:
        return f"Error: Request timed out after {REQUEST_TIMEOUT}s. Try a shorter query or increase timeout."
    except requests.exceptions.ConnectionError:
        return "Error: Cannot connect to Ollama. Run: ollama serve"
    except Exception as e:
        return f"Error: {str(e)}"

def query_ollama(prompt: str, context: str) -> str:
    """Query Ollama (non-streaming fallback)."""
    try:
        full_prompt = f"""You are a retail analysis assistant.

Use the following retail analysis data to answer the user's question:

{context}

User Question: {prompt}

Provide a detailed response based on the data. If no relevant info exists, respond with: 'No suitable response found error'"""
        
        response = requests.post(
            OLLAMA_API_URL,
            json={
                "model": MODEL_NAME,
                "prompt": full_prompt,
                "stream": False,
                "temperature": 0.7,
            },
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code == 200:
            return response.json()['response']
        else:
            return f"Error: {response.status_code}"
    
    except requests.exceptions.Timeout:
        return f"Error: Request timed out. Try a simpler query."
    except requests.exceptions.ConnectionError:
        return "Error: Cannot connect to Ollama"
    except Exception as e:
        return f"Error: {str(e)}"

def export_to_csv(data: List[dict], filename: str) -> str:
    """Export data to CSV."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"{filename}_{timestamp}.csv"
        output_path = os.path.join(GENAI_OUTPUT_FOLDER, output_filename)
        
        if not data:
            return "No data to export"
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        
        return f"Successfully exported to {output_filename}"
    
    except Exception as e:
        return f"Error exporting: {str(e)}"

def parse_simulation_response(response: str) -> Tuple[bool, List[dict]]:
    """Parse CSV from response."""
    try:
        lines = response.strip().split('\n')
        
        if len(lines) < 2:
            return False, []
        
        header_line = lines[0].strip()
        if ',' not in header_line:
            return False, []
        
        headers = [h.strip() for h in header_line.split(',')]
        data = []
        
        for line in lines[1:]:
            if line.strip() and not line.startswith('['):
                values = [v.strip() for v in line.split(',')]
                if len(values) == len(headers):
                    data.append(dict(zip(headers, values)))
        
        return len(data) > 0, data
    
    except Exception:
        return False, []

def main():
    st.set_page_config(page_title="Retail Analysis RAG Agent", layout="wide")
    
    st.title("Retail Analysis RAG Agent")
    st.markdown("Optimized with streaming & context limiting")
    
    # Load CSV files with row limiting
    csv_files = load_csv_files(limit_rows=True)
    
    # Sidebar
    with st.sidebar:
        st.header("Status")
        
        ollama_healthy, health_msg = check_ollama_health()
        if ollama_healthy:
            st.success("✅ " + health_msg)
        else:
            st.error("❌ " + health_msg)
        
        st.write(f"CSV Files: {len(csv_files)}")
        
        if csv_files:
            with st.expander("View Loaded Files"):
                for filename in csv_files.keys():
                    st.write(f"• {filename}")
        
        st.divider()
        st.markdown("**Configuration**")
        st.write(f"Model: {MODEL_NAME}")
        st.write(f"Timeout: {REQUEST_TIMEOUT}s")
        st.write(f"Max Context: {MAX_CONTEXT_SIZE} chars")
        st.write(f"Streaming: {STREAM_RESPONSE}")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        query_type = st.radio(
            "Select Query Type:",
            ["General Analysis Query", "Create Simulation Scenario"]
        )
    
    if query_type == "General Analysis Query":
        st.subheader("Query Retail Analysis Data")
        
        if not csv_files:
            st.error("No CSV files in 'retail_analysis_output' folder")
        else:
            user_query = st.text_area(
                "Enter your question:",
                placeholder="e.g., What are top products? Summarize trends...",
                height=80
            )
            
            col1, col2 = st.columns(2)
            with col1:
                analyze_btn = st.button("🔍 Analyze", use_container_width=True)
            with col2:
                if st.button("📋 View Context Size"):
                    context = build_context(csv_files)
                    st.info(f"Context size: {len(context)} chars")
            
            if analyze_btn:
                if user_query.strip():
                    with st.spinner("Processing..."):
                        context = build_context(csv_files)
                        
                        # Use streaming for real-time feedback
                        response_container = st.empty()
                        full_response = ""
                        
                        for partial_response in query_ollama_streaming(user_query, context):
                            full_response = partial_response
                            response_container.markdown(full_response)
                    
                    st.subheader("Final Response")
                    st.markdown(full_response)
                else:
                    st.warning("Enter a query")
    
    else:  # Create Simulation Scenario
        st.subheader("Create Simulation Scenario")
        
        if not csv_files:
            st.error("No CSV files available")
        else:
            scenario_description = st.text_area(
                "Describe the scenario:",
                placeholder="e.g., Generate Q4 sales forecast with 20% growth...",
                height=80
            )
            
            scenario_name = st.text_input("Scenario Name:", value="simulation")
            
            if st.button("🎬 Generate Simulation", use_container_width=True):
                if scenario_description.strip():
                    with st.spinner("Generating..."):
                        context = build_context(csv_files)
                        
                        prompt = f"""{scenario_description}

Generate output in CSV format with headers in the first row and data in subsequent rows. Be concise."""
                        
                        response = query_ollama(prompt, context)
                    
                    has_data, parsed_data = parse_simulation_response(response)
                    
                    if has_data:
                        export_msg = export_to_csv(parsed_data, scenario_name)
                        st.success(f"✅ {export_msg}")
                        st.dataframe(parsed_data, use_container_width=True)
                    else:
                        st.info("Raw Response:")
                        st.text(response)
                else:
                    st.warning("Describe a scenario")
    
    st.divider()
    st.markdown("""
    **Optimization Tips:**
    - Large CSV files are truncated to first 100 rows
    - Context is limited to 8000 chars to prevent timeouts
    - Streaming shows responses in real-time
    - Timeout set to 120s for typical queries
    """)

if __name__ == "__main__":
    main()
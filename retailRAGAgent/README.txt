About:
This codebase goes with the solution built to demonstrate the power of LLMs operating on your organizational data.

Pre-requisities:
1. Ollama 
2. Streamlit

This solution comprises of the following files:

1. retail_sales.csv - Proxy for your enterprise sales data. The content is for demonstration purposes only. Please augment with actual data volume or connect with your source to get realistics results.
2. 1_generateRetailAnalysis.py - Python script to generate relevant data chunks for feeding Gen AI agent. The output will be written to a folder called retail_analysis_output. I've provided that here as a reference. 
3. 2_retailDashboard.py - Standalone streamlit based app for offering supply chain visibility
4. 3_retailgenaiapp.py - Generative AI powered app built on Streamlit, Ollama running Mistral LLM (option to switch out to Gem3)


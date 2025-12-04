import json
import pandas as pd
import numpy as np
from datetime import datetime
import requests
import csv
import os
from concurrent.futures import ThreadPoolExecutor
import time

class FeedbackAnalyzer:
    def __init__(self, json_file='feedback_data.json', api_key=None):
        self.json_file = json_file
        self.df = None
        self.api_key = api_key or os.getenv('OLLAMA_API_KEY')
        self.api_url = "http://localhost:11434/v1/chat/completions"
        # Session for connection pooling
        self.session = requests.Session()

    def load_data(self):
        """Load JSON data into a pandas DataFrame with optimized dtypes"""
        with open(self.json_file, 'r') as f:
            data = json.load(f)
        
        # Convert to DataFrame with optimized dtypes
        self.df = pd.DataFrame(data)
        
        # Optimize dtypes to reduce memory usage
        self.df['Product_id'] = self.df['Product_id'].astype('category')
        self.df['Location'] = self.df['Location'].astype('category')
        self.df['Comment_Date'] = pd.to_datetime(self.df['Comment_Date'], cache=True)
        self.df['Rating'] = self.df['Rating'].astype('int8')
        
        print(f"Loaded {len(self.df)} records from {self.json_file}")
        return self.df
    
    def invoke_mistral3(self, prompt, temperature=0.7, max_tokens=2048):
        """Invoke MISTRAL model via Ollama with optimized settings"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": "mistral",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx": 4096  # Context window
            }
        }
        
        try:
            response = self.session.post(self.api_url, json=payload, headers=headers, timeout=540)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            print(f"Error calling Ollama API: {e}")
            return None
    
    def analyze_data_with_llm(self):
        """Use mistral to analyze data patterns with condensed prompt"""
        # Create more efficient summary
        summary = {
            'total_records': len(self.df),
            'avg_rating': round(float(self.df['Rating'].mean()), 2),
            'rating_dist': self.df['Rating'].value_counts().to_dict(),
            'products': self.df['Product_id'].nunique(),
            'locations': self.df['Location'].nunique(),
            'date_range': f"{self.df['Comment_Date'].min().date()} to {self.df['Comment_Date'].max().date()}"
        }
        
        # Condensed sample data - only essential columns
        sample_df = self.df[['Product_id', 'Location', 'Rating', 'Comment_Date']].head(5)
        
        prompt = f"""Analyze this feedback dataset quickly:

Stats: {json.dumps(summary)}
Sample: {sample_df.to_string(index=False)}

Provide brief insights (3-4 sentences) on:
1. Rating patterns across products/locations
2. Notable trends
3. Key satisfaction factors"""
        
        print("\nAnalyzing data with MISTRAL...")
        start = time.time()
        analysis = self.invoke_mistral3(prompt, temperature=0.5, max_tokens=500)
        print(f"Analysis completed in {time.time() - start:.2f}s")
        print("\n=== LLM Analysis ===")
        print(analysis)
        return analysis
    
    def compute_correlation_factors(self):
        """Optimized correlation computation using vectorized operations"""
        # Pre-convert dates once
        self.df['date_ordinal'] = self.df['Comment_Date'].apply(lambda x: x.toordinal())
        
        results = []
        grouped = self.df.groupby(['Product_id', 'Location'], observed=True)
        
        for (product, location), group in grouped:
            if len(group) < 2:
                continue
            
            ratings = group['Rating'].values
            dates = group['date_ordinal'].values
            
            # Fast correlation calculation
            if len(ratings) > 1 and ratings.std() > 0:
                correlation = np.corrcoef(dates, ratings)[0, 1]
                correlation = 0.0 if np.isnan(correlation) else correlation
            else:
                correlation = 0.0
            
            # Get most recent date
            demand_date = group['Comment_Date'].max().strftime('%Y-%m-%d')
            
            results.append({
                'Product': product,
                'Location': location,
                'Demand_Date': demand_date,
                'Correlation_Factor': round(correlation, 4)
            })
        
        return pd.DataFrame(results)
    
    def save_correlation_results(self, output_file='correlation_results.csv'):
        """Save correlation analysis to CSV"""
        print("\nComputing correlations...")
        start = time.time()
        correlation_df = self.compute_correlation_factors()
        print(f"Correlations computed in {time.time() - start:.2f}s")
        
        correlation_df.to_csv(output_file, index=False)
        print(f"Results saved to {output_file}")
        print(f"\nPreview ({len(correlation_df)} total):")
        print(correlation_df.head(10))
        return correlation_df
    
    def generate_llm_insights(self, correlation_df):
        """Generate insights with condensed prompt"""
        # Show top/bottom correlations for faster processing
        top_5 = correlation_df.nlargest(5, 'Correlation_Factor')
        bottom_5 = correlation_df.nsmallest(5, 'Correlation_Factor')
        
        prompt = f"""Analyze these correlation results (rating vs time):

TOP 5 IMPROVING:
{top_5.to_string(index=False)}

BOTTOM 5 DECLINING:
{bottom_5.to_string(index=False)}

Provide brief insights (4-5 sentences):
1. Which Product-Locations are improving?
2. Which are declining?
3. Top 2 recommendations

Note: Correlation -1 to 1 (positive = improving, negative = declining)"""
        
        print("\n=== Generating Insights ===")
        start = time.time()
        insights = self.invoke_mistral3(prompt, temperature=0.5, max_tokens=500)
        print(f"Insights generated in {time.time() - start:.2f}s")
        print(insights)
        return insights
    
    def run_parallel_analysis(self, correlation_df):
        """Optional: Run both LLM analyses in parallel"""
        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(self.analyze_data_with_llm)
            future2 = executor.submit(self.generate_llm_insights, correlation_df)
            
            analysis = future1.result()
            insights = future2.result()
            
        return analysis, insights

def main():
    start_time = time.time()
    
    api_key = os.getenv('OLLAMA_API_KEY', 'dummy_key')  # Local doesn't need real key
    analyzer = FeedbackAnalyzer('feedback_data.json', api_key=api_key)
    
    # Load data with optimizations
    df = analyzer.load_data()
    
    # Compute correlations first (faster, no LLM)
    correlation_df = analyzer.save_correlation_results('correlation_results.csv')
    
    # LLM analyses (can be skipped for even faster execution)
    print("\n" + "="*50)
    print("Running LLM analyses (can take 30-60s)...")
    print("="*50)
    
    analyzer.analyze_data_with_llm()
    analyzer.generate_llm_insights(correlation_df)
    
    print(f"\n{'='*50}")
    print(f"Total execution time: {time.time() - start_time:.2f}s")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
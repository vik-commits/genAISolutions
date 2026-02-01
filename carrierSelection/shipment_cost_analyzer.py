import pandas as pd
import requests
import json
from typing import Dict, List
import time


class ShipmentCostAnalyzer:
    """
    Analyzes shipment costs using Ollama LLM to scan multiple shipping sources
    and find the lowest cost option for each shipment.
    """
    
    def __init__(self, ollama_url: str = "http://localhost:11434", model: str = "mistral"):
        """
        Initialize the analyzer with Ollama configuration.
        
        Args:
            ollama_url: URL of the Ollama API endpoint
            model: Name of the Ollama model to use (e.g., 'llama2', 'mistral')
        """
        self.ollama_url = ollama_url
        self.model = model
        self.api_endpoint = f"{ollama_url}/api/generate"
        
    def call_ollama(self, prompt: str) -> str:
        """
        Call Ollama LLM with a prompt and return the response.
        
        Args:
            prompt: The prompt to send to the LLM
            
        Returns:
            The LLM's response as a string
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False
        }
        
        try:
            response = requests.post(self.api_endpoint, json=payload, timeout=5000)
            response.raise_for_status()
            return response.json()['response']
        except requests.exceptions.RequestException as e:
            print(f"Error calling Ollama: {e}")
            return ""
    
    def get_shipping_quote_prompt(self, ship_from: str, ship_to: str, weight: float) -> str:
        """
        Create a prompt for the LLM to find shipping quotes.
        
        Args:
            ship_from: Origin zip code
            ship_to: Destination zip code
            weight: Parcel weight in pounds
            
        Returns:
            Formatted prompt string
        """
        prompt = f"""You are a shipping cost analysis assistant. I need you to find shipping costs from multiple carriers and sources for a parcel with the following details:

Ship From Zip Code: {ship_from}
Ship To Zip Code: {ship_to}
Parcel Weight: {weight} lbs

Please provide shipping quotes from the following sources:
1. Parcel Monkey (parcelmonkey.com)
2. netParcel (netparcel.com)
3. Shippo (goshippo.com)

For each source, consider major carriers like USPS, UPS, FedEx, and DHL.

Respond ONLY in the following JSON format (no additional text):
{{
    "all_quotes": [
        {{
            "carrier": "USPS Priority",
            "cost": 12.50,
            "source": "Parcel Monkey"
        }},
        {{
            "carrier": "UPS Ground",
            "cost": 15.75,
            "source": "netParcel"
        }},
        {{
            "carrier": "FedEx Ground",
            "cost": 13.20,
            "source": "Shippo"
        }}
    ],
    "lowest_cost_option": {{
        "carrier": "USPS Priority",
        "cost": 12.50,
        "source": "Parcel Monkey"
    }}
}}

Important: 
- Provide realistic estimates based on typical shipping rates for this route and weight
- Include at least 3-6 different carrier options from different sources
- Identify the absolute lowest cost option in the lowest_cost_option field
"""
        return prompt
    
    def parse_llm_response(self, response: str) -> Dict:
        """
        Parse the LLM response to extract all carrier quotes and the lowest cost option.
        
        Args:
            response: Raw LLM response
            
        Returns:
            Dictionary with all_quotes and lowest_cost_option
        """
        try:
            # Try to find JSON in the response
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            
            if start_idx != -1 and end_idx != 0:
                json_str = response[start_idx:end_idx]
                data = json.loads(json_str)
                
                # Extract all quotes
                all_quotes = []
                if 'all_quotes' in data and isinstance(data['all_quotes'], list):
                    all_quotes = data['all_quotes']
                
                # Extract lowest cost option
                lowest = data.get('lowest_cost_option', {})
                if not lowest and all_quotes:
                    # If lowest not specified, find it from all_quotes
                    lowest = min(all_quotes, key=lambda x: float(x.get('cost', float('inf'))))
                
                return {
                    'all_quotes': all_quotes,
                    'lowest_cost_option': {
                        'carrier': lowest.get('carrier', 'Unknown'),
                        'cost': float(lowest.get('cost', 0.0)),
                        'source': lowest.get('source', 'Unknown')
                    },
                    'raw_llm_response': response
                }
            else:
                # Fallback parsing if JSON not found
                return {
                    'all_quotes': [],
                    'lowest_cost_option': {
                        'carrier': 'Unknown',
                        'cost': 0.0,
                        'source': 'Unknown'
                    },
                    'raw_llm_response': response
                }
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Error parsing LLM response: {e}")
            print(f"Response was: {response}")
            return {
                'all_quotes': [],
                'lowest_cost_option': {
                    'carrier': 'Unknown',
                    'cost': 0.0,
                    'source': 'Unknown'
                },
                'raw_llm_response': response
            }
    
    def analyze_shipment(self, shipment_id: str, ship_from: str, 
                        ship_to: str, weight: float) -> Dict:
        """
        Analyze a single shipment to find the lowest cost.
        
        Args:
            shipment_id: Unique shipment identifier
            ship_from: Origin zip code
            ship_to: Destination zip code
            weight: Parcel weight
            
        Returns:
            Dictionary with shipment details, all carrier quotes, and lowest cost information
        """
        print(f"Analyzing shipment {shipment_id}...")
        
        prompt = self.get_shipping_quote_prompt(ship_from, ship_to, weight)
        llm_response = self.call_ollama(prompt)
        
        if not llm_response:
            return {
                'Shipment_ID': shipment_id,
                'Ship_From': ship_from,
                'Ship_To': ship_to,
                'Parcel_Weight': weight,
                'All_Carrier_Options': [],
                'Lowest_Cost_Carrier': 'Error',
                'Lowest_Cost': 0.0,
                'Lowest_Cost_Source': 'Error',
                'LLM_Raw_Response': 'Error: No response from LLM'
            }
        
        parsed_data = self.parse_llm_response(llm_response)
        lowest = parsed_data['lowest_cost_option']
        
        return {
            'Shipment_ID': shipment_id,
            'Ship_From': ship_from,
            'Ship_To': ship_to,
            'Parcel_Weight': weight,
            'All_Carrier_Options': parsed_data['all_quotes'],
            'Lowest_Cost_Carrier': lowest['carrier'],
            'Lowest_Cost': lowest['cost'],
            'Lowest_Cost_Source': lowest['source'],
            'LLM_Raw_Response': parsed_data['raw_llm_response']
        }
    
    def process_csv(self, input_file: str, output_file: str, delay: float = 1.0):
        """
        Process all shipments from a CSV file and save results to JSON.
        
        Args:
            input_file: Path to input CSV file
            output_file: Path to output JSON file
            delay: Delay in seconds between API calls to avoid rate limiting
        """
        try:
            # Read input CSV
            df = pd.read_csv(input_file)
            
            # Validate required columns
            required_columns = ['Shipment_ID', 'Ship_From', 'Ship_To', 'Parcel_weight']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                raise ValueError(f"Missing required columns: {missing_columns}")
            
            # Process each shipment
            shipments = []
            total_shipments = len(df)
            total_cost = 0.0
            carrier_counts = {}
            source_counts = {}
            
            for idx, row in df.iterrows():
                print(f"\nProcessing {idx + 1}/{total_shipments}")
                
                result = self.analyze_shipment(
                    shipment_id=row['Shipment_ID'],
                    ship_from=str(row['Ship_From']),
                    ship_to=str(row['Ship_To']),
                    weight=float(row['Parcel_weight'])
                )
                
                shipments.append(result)
                
                # Calculate statistics
                total_cost += result['Lowest_Cost']
                carrier = result['Lowest_Cost_Carrier']
                source = result['Lowest_Cost_Source']
                
                carrier_counts[carrier] = carrier_counts.get(carrier, 0) + 1
                source_counts[source] = source_counts.get(source, 0) + 1
                
                # Add delay to avoid overwhelming the LLM
                if idx < total_shipments - 1:
                    time.sleep(delay)
            
            # Compile complete JSON output
            output_data = {
                "metadata": {
                    "total_shipments": total_shipments,
                    "total_estimated_cost": round(total_cost, 2),
                    "processing_date": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "input_file": input_file,
                    "ollama_model": self.model
                },
                "summary": {
                    "carrier_breakdown": carrier_counts,
                    "source_breakdown": source_counts
                },
                "shipments": shipments
            }
            
            # Save to JSON file with pretty formatting
            with open(output_file, 'w') as f:
                json.dump(output_data, f, indent=2)
            
            print(f"\n Results saved to {output_file}")
            
            # Display summary
            print("\n=== Summary ===")
            print(f"Total shipments processed: {total_shipments}")
            print(f"Total estimated cost: ${total_cost:.2f}")
            print("\nCarrier breakdown:")
            for carrier, count in carrier_counts.items():
                print(f"  {carrier}: {count}")
            print("\nSource breakdown:")
            for source, count in source_counts.items():
                print(f"  {source}: {count}")
            
            return output_data
            
        except FileNotFoundError:
            print(f"Error: Input file '{input_file}' not found.")
        except Exception as e:
            print(f"Error processing CSV: {e}")
            raise


def main():
    """
    Main function to run the shipment cost analyzer.
    """
    # Configuration
    INPUT_CSV = "shipments.csv"
    OUTPUT_JSON = "shipment_costs_output.json"
    OLLAMA_URL = "http://localhost:11434"
    MODEL_NAME = "llama2"  # Change to your preferred model (llama2, mistral, etc.)
    
    print("=" * 60)
    print("Shipment Cost Analyzer using LLM")
    print("=" * 60)
    print(f"Input file: {INPUT_CSV}")
    print(f"Output file: {OUTPUT_JSON}")
    print(f"Ollama URL: {OLLAMA_URL}")
    print(f"Model: {MODEL_NAME}")
    print("=" * 60)
    
    # Create analyzer instance
    analyzer = ShipmentCostAnalyzer(ollama_url=OLLAMA_URL, model=MODEL_NAME)
    
    # Process shipments
    try:
        analyzer.process_csv(INPUT_CSV, OUTPUT_JSON, delay=1.0)
    except Exception as e:
        print(f"\n Failed to process shipments: {e}")


if __name__ == "__main__":
    main()

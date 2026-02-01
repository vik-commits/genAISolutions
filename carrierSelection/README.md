# Shipment Cost Analyzer using Ollama LLM

This Python script analyzes shipment costs by using Ollama LLM to scan multiple shipping sources (Parcel Monkey, netParcel, and Shippo) and determine the lowest cost carrier for each shipment.

## Features

- Reads shipment data from CSV file
- Uses Ollama LLM to analyze shipping costs from multiple sources
- Identifies the lowest cost carrier for each shipment
- **Outputs results to JSON file with complete shipment data and summary statistics**
- Provides summary statistics

## Prerequisites

1. **Python 3.7+** installed on your system
2. **Ollama** installed and running locally
3. Required Python packages (see Installation)

## Installation

### 1. Install Ollama

Download and install Ollama from: https://ollama.ai/

After installation, pull a model (e.g., llama2):
```bash
ollama pull llama2
# Or use other models like:
# ollama pull mistral
# ollama pull codellama
```

Start Ollama (it usually starts automatically):
```bash
ollama serve
```

### 2. Install Python Dependencies

```bash
pip install pandas requests
```

## Input CSV Format

Your input CSV file must contain the following columns:

| Column | Description |
|--------|-------------|
| `Shipment_ID` | Unique shipment identifier |
| `Ship_From` | Origin zip code |
| `Ship_To` | Destination zip code |
| `Parcel_weight` | Weight of the parcel (in pounds) |

**Example (`shipments.csv`):**
```csv
Shipment_ID,Ship_From,Ship_To,Parcel_weight
SHP001,10001,90210,5.5
SHP002,60601,33101,12.0
SHP003,94102,02108,3.2
```

## Usage

### Basic Usage

```bash
python shipment_cost_analyzer.py
```

By default, the script will:
- Read from `shipments.csv`
- Output to `shipment_costs_output.json`
- Use Ollama at `http://localhost:11434`
- Use the `llama2` model

### Custom Configuration

Edit the `main()` function in the script to customize:

```python
# Configuration
INPUT_CSV = "your_shipments.csv"
OUTPUT_JSON = "your_output.json"
OLLAMA_URL = "http://localhost:11434"
MODEL_NAME = "mistral"  # or llama2, codellama, etc.
```

### Programmatic Usage

```python
from shipment_cost_analyzer import ShipmentCostAnalyzer

# Create analyzer
analyzer = ShipmentCostAnalyzer(
    ollama_url="http://localhost:11434",
    model="llama2"
)

# Process CSV and get JSON output
results = analyzer.process_csv(
    input_file="shipments.csv",
    output_file="results.json",
    delay=1.0  # seconds between requests
)

# Or analyze individual shipment
result = analyzer.analyze_shipment(
    shipment_id="SHP001",
    ship_from="10001",
    ship_to="90210",
    weight=5.5
)
print(result)
```

## Output Format

The output JSON file will contain a comprehensive structure with metadata, summary statistics, and detailed shipment information including all carrier options and the raw LLM response:

```json
{
  "metadata": {
    "total_shipments": 5,
    "total_estimated_cost": 62.45,
    "processing_date": "2026-01-31 14:30:22",
    "input_file": "shipments.csv",
    "ollama_model": "llama2"
  },
  "summary": {
    "carrier_breakdown": {
      "USPS Priority": 2,
      "UPS Ground": 1,
      "FedEx Ground": 1
    },
    "source_breakdown": {
      "Parcel Monkey": 2,
      "netParcel": 2,
      "Shippo": 1
    }
  },
  "shipments": [
    {
      "Shipment_ID": "SHP001",
      "Ship_From": "10001",
      "Ship_To": "90210",
      "Parcel_Weight": 5.5,
      "All_Carrier_Options": [
        {
          "carrier": "USPS Priority",
          "cost": 12.50,
          "source": "Parcel Monkey"
        },
        {
          "carrier": "UPS Ground",
          "cost": 15.75,
          "source": "netParcel"
        },
        {
          "carrier": "FedEx Ground",
          "cost": 14.20,
          "source": "Shippo"
        }
      ],
      "Lowest_Cost_Carrier": "USPS Priority",
      "Lowest_Cost": 12.50,
      "Lowest_Cost_Source": "Parcel Monkey",
      "LLM_Raw_Response": "{\"all_quotes\": [...], \"lowest_cost_option\": {...}}"
    }
    // ... more shipments
  ]
}
```

### JSON Structure:

**metadata**: Overall processing information
- `total_shipments`: Number of shipments processed
- `total_estimated_cost`: Sum of all lowest carrier costs
- `processing_date`: When the analysis was run
- `input_file`: Source CSV filename
- `ollama_model`: LLM model used for analysis

**summary**: Aggregated statistics
- `carrier_breakdown`: Count of shipments by lowest cost carrier
- `source_breakdown`: Count of shipments by lowest cost source

**shipments**: Array of individual shipment results (each contains):
- `Shipment_ID`: Original shipment ID
- `Ship_From`: Origin zip code
- `Ship_To`: Destination zip code
- `Parcel_Weight`: Weight in pounds
- `All_Carrier_Options`: Array of all carrier quotes found by the LLM
  - `carrier`: Carrier name and service level
  - `cost`: Shipping cost in USD
  - `source`: Web source (Parcel Monkey, netParcel, or Shippo)
- `Lowest_Cost_Carrier`: The carrier with the absolute lowest cost
- `Lowest_Cost`: The lowest cost found
- `Lowest_Cost_Source`: Source that provided the lowest cost
- `LLM_Raw_Response`: Complete raw response from the LLM (for debugging/verification)

## Important Notes

### ⚠️ LLM Limitations

**This script uses LLM to SIMULATE shipping cost lookups. The LLM does NOT actually access the shipping websites in real-time.** 

The costs returned are:
- **Estimates** based on the LLM's training data
- **NOT real-time quotes** from the actual shipping services
- Subject to hallucination and inaccuracy

### For Production Use

To get REAL shipping quotes, you would need to:

1. **Use actual APIs** from shipping services:
   - Shippo API: https://goshippo.com/docs/
   - EasyPost API: https://www.easypost.com/docs/api
   - ShipEngine API: https://www.shipengine.com/docs/

2. **Example using Shippo API:**
```python
import shippo

shippo.api_key = "YOUR_API_KEY"

# Create shipment
shipment = shippo.Shipment.create(
    address_from={...},
    address_to={...},
    parcels=[{...}]
)

# Get rates
rates = shipment.rates
lowest_rate = min(rates, key=lambda x: float(x.amount))
```

3. **Web scraping** (check terms of service):
   - Use libraries like Selenium or Playwright
   - Respect robots.txt and rate limits
   - May violate ToS of some sites

## Troubleshooting

### Ollama Connection Error

```
Error calling Ollama: Connection refused
```

**Solution:** Make sure Ollama is running:
```bash
ollama serve
```

### Model Not Found

```
Error: model 'llama2' not found
```

**Solution:** Pull the model first:
```bash
ollama pull llama2
```

### Parsing Errors

If you see JSON parsing errors, the LLM may not be following the format. Try:
- Using a different model (mistral often works well)
- Adjusting the prompt
- Adding more examples to the prompt

### Rate Limiting

If processing many shipments, increase the delay:
```python
analyzer.process_csv(input_file, output_file, delay=2.0)  # 2 second delay
```

## Performance

- Processing time: ~2-5 seconds per shipment (depending on model)
- For 100 shipments: ~5-10 minutes
- Consider batch processing for large datasets

## License

This is a demonstration script. Use at your own risk.

## Disclaimer

This tool provides ESTIMATED shipping costs using AI. Always verify costs with actual carrier websites or APIs before making business decisions.

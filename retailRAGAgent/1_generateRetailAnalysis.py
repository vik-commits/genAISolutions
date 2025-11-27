import pandas as pd
import os
import sys
from datetime import datetime


class RetailAnalysisAgent:
    
    def __init__(self, input_csv_path, output_dir='retail_analysis_output'):
        self.input_csv = input_csv_path
        self.output_dir = output_dir
        self.df = None
        
        # Create output directory
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            print(f"✓ Created output directory: {output_dir}")
    
    def load_data(self):
        """Load and validate CSV file"""
        try:
            self.df = pd.read_csv(self.input_csv)
            print(f"✓ Data loaded successfully")
            print(f"  Shape: {self.df.shape}")
            print(f"  Columns: {list(self.df.columns)}")
            return True
        except Exception as e:
            print(f"✗ Error loading CSV: {e}")
            return False
    
    def process_all(self):
        """Execute all analysis tasks"""
        if not self.load_data():
            return False
        
        print("\n" + "="*60)
        print("Processing Retail Sales Data")
        print("="*60 + "\n")
        
        # Convert Date to datetime
        self.df['Date'] = pd.to_datetime(self.df['Date'])
        
        # Task 1: Total Sales by Category & Month
        self._sales_by_category_month()
        
        # Task 2: Total Sales by Category & Gender
        self._sales_by_category_gender()
        
        # Task 3: Top Product Categories by Total Sales Amount
        self._top_categories()
        
        # Task 4: Total Sales Aggregated by Month
        self._sales_by_month()
        
        # Task 5: Total Sales Amount by Category & Gender (detailed)
        self._sales_category_gender_detailed()
        
        print("\n" + "="*60)
        print(f"✓ All analysis files generated successfully!")
        print(f"  Output directory: {self.output_dir}")
        print("="*60)
        return True
    
    def _sales_by_category_month(self):
        """1. Total Sales by Category, Month"""
        df_temp = self.df.copy()
        df_temp['Month'] = df_temp['Date'].dt.to_period('M')
        
        result = df_temp.groupby(['Product Category', 'Month'])['Total Amount'].sum().reset_index()
        result['Month'] = result['Month'].astype(str)
        result = result.sort_values(['Product Category', 'Month'])
        
        output_path = os.path.join(self.output_dir, '1_sales_by_category_month.csv')
        result.to_csv(output_path, index=False)
        print(f"✓ Task 1: Total Sales by Category & Month")
        print(f"  File: 1_sales_by_category_month.csv")
        print(f"  Rows: {len(result)}")
    
    def _sales_by_category_gender(self):
        """2. Total Sales by Category, Gender"""
        result = self.df.groupby(['Product Category', 'Gender'])['Total Amount'].sum().reset_index()
        result = result.sort_values(['Product Category', 'Gender'])
        
        output_path = os.path.join(self.output_dir, '2_sales_by_category_gender.csv')
        result.to_csv(output_path, index=False)
        print(f"✓ Task 2: Total Sales by Category & Gender")
        print(f"  File: 2_sales_by_category_gender.csv")
        print(f"  Rows: {len(result)}")
    
    def _top_categories(self):
        """3. Top Product Categories by Total Sales Amount"""
        result = self.df.groupby('Product Category')['Total Amount'].sum().reset_index()
        result.columns = ['Product Category', 'Total Sales Amount']
        result = result.sort_values('Total Sales Amount', ascending=False)
        
        output_path = os.path.join(self.output_dir, '3_top_categories.csv')
        result.to_csv(output_path, index=False)
        print(f"✓ Task 3: Top Product Categories by Total Sales")
        print(f"  File: 3_top_categories.csv")
        print(f"  Rows: {len(result)}")
    
    def _sales_by_month(self):
        """4. Total Sales Aggregated by Month"""
        df_temp = self.df.copy()
        df_temp['Month'] = df_temp['Date'].dt.to_period('M')
        
        result = df_temp.groupby('Month')['Total Amount'].sum().reset_index()
        result.columns = ['Month', 'Total Sales Amount']
        result['Month'] = result['Month'].astype(str)
        result = result.sort_values('Month')
        
        output_path = os.path.join(self.output_dir, '4_sales_by_month.csv')
        result.to_csv(output_path, index=False)
        print(f"✓ Task 4: Total Sales Aggregated by Month")
        print(f"  File: 4_sales_by_month.csv")
        print(f"  Rows: {len(result)}")
    
    def _sales_category_gender_detailed(self):
        """5. Total Sales Amount by Category, Gender (detailed)"""
        result = self.df.groupby(['Product Category', 'Gender']).agg({
            'Total Amount': ['sum', 'count', 'mean']
        }).reset_index()
        
        result.columns = ['Category', 'Gender', 'Total Sales Amount', 'Transaction Count', 'Average Sales']
        result = result.sort_values(['Category', 'Gender'])
        
        output_path = os.path.join(self.output_dir, '5_sales_category_gender.csv')
        result.to_csv(output_path, index=False)
        print(f"✓ Task 5: Sales by Category & Gender (Detailed)")
        print(f"  File: 5_sales_category_gender.csv")
        print(f"  Rows: {len(result)}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python retail_agent.py <path_to_input_csv>")
        print("\nExample:")
        print("  python retail_agent.py retail_sales.csv")
        sys.exit(1)
    
    input_csv = sys.argv[1]
    
    if not os.path.exists(input_csv):
        print(f"✗ Error: File '{input_csv}' not found")
        sys.exit(1)
    
    agent = RetailAnalysisAgent(input_csv)
    success = agent.process_all()
    
    if success:
        print("\n✓ Ready to use Streamlit app!")
        print("  Run: streamlit run retail_dashboard.py")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
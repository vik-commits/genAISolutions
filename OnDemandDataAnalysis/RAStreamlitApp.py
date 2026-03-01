import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

# --- Load & normalize ---
data = pd.read_csv('retaildata.csv')
data.columns = data.columns.str.strip()
data = data.rename(columns={
    'country':               'Country',
    'product_name':          'Product',
    'product_rating_count':  'Sales',
    'price':                 'Price',
    'product_rating':        'Product_ratings',
})
# Ensure numeric types
data['Sales']           = pd.to_numeric(data['Sales'],           errors='coerce').fillna(0)
data['Price']           = pd.to_numeric(data['Price'],           errors='coerce').fillna(0)
data['Product_ratings'] = pd.to_numeric(data['Product_ratings'], errors='coerce').fillna(0)


st.title("Retail Data Analysis")
st.text("")
st.text("")
st.write("**Ad-hoc dashboard created using LLMs**")

# --- Functions ---

def get_product_counts_by_country(df):
    grouped = df.groupby(['Country', 'Product'])['Sales'].sum().unstack()
    return grouped.fillna(0)


def get_top_5_products_by_country(df, country):
    country_df = df[df['Country'] == country]
    top5 = country_df.groupby('Product')['Sales'].sum().nlargest(5)
    prices = country_df.groupby('Product')['Price'].mean().loc[top5.index]
    return pd.DataFrame({'Product': top5.index, 'Price': prices.values})


def get_top_100_products_by_price(df):
    top100 = (
        df.groupby('Product')['Price']
        .mean()
        .nlargest(100)
        .reset_index()
    )
    countries_per_product = (
        df[df['Product'].isin(top100['Product'])]
        .groupby('Product')['Country']
        .apply(lambda x: ', '.join(sorted(x.unique())))
        .reset_index()
        .rename(columns={'Country': 'Countries Sold In'})
    )
    return top100.merge(countries_per_product, on='Product')


def get_country_sales_info(df):
    total_sales   = df.groupby('Country')['Sales'].sum().reset_index()
    currency_info = df.groupby('Country')['currency'].first().reset_index()
    total_sales   = total_sales.merge(currency_info, on='Country', how='left')
    projected     = df.groupby('Country').apply(
        lambda x: (x['Price'] * 100).sum()
    ).reset_index(name='Projected Sales')
    total_sales   = total_sales.merge(projected, on='Country', how='left')
    # No conversion rate in data — flag accordingly
    total_sales['Total in US $'] = 'N/A (no conversion rate in data)'
    return total_sales[['Country', 'Sales', 'currency', 'Projected Sales', 'Total in US $']]


def get_top_5_products_by_rating(df, country):
    country_df = df[df['Country'] == country]
    top5 = country_df.groupby('Product')['Product_ratings'].mean().nlargest(5)
    return pd.DataFrame({'Product': top5.index, 'Rating': top5.values})


def get_query_results(question):
    words = question.strip().split()

    if len(words) == 1 and words[0].lower() == "help":
        return ("Welcome! You can ask questions about the sales data.\n"
                "Examples:\n"
                "  - 'ORDNING' to look up a product\n"
                "  - 'Australia' to look up a country")

    pattern = '|'.join(words)

    product_mask = data['Product'].str.contains(pattern, case=False, na=False)
    if product_mask.any():
        product = data.loc[product_mask, 'Product'].iloc[0]
        sales_data = data[data['Product'] == product]
        countries = sales_data['Country'].unique()
        sales_by_country = sales_data.groupby('Country')['Sales'].sum()
        return (f"Product: {product}\n"
                f"Countries sold in: {', '.join(countries)}\n"
                f"Sales by Country:\n{sales_by_country.to_string()}")

    country_mask = data['Country'].str.contains(pattern, case=False, na=False)
    if country_mask.any():
        country = data.loc[country_mask, 'Country'].iloc[0]
        sales_data = data[data['Country'] == country]
        top5 = sales_data.sort_values('Price', ascending=False).head(5)
        return (f"Data for {country}:\n"
                f"Total Sales: {sales_data['Sales'].sum()}\n"
                f"Top 5 Products by Price:\n"
                f"{top5[['Product', 'Price']].to_string(index=False)}")

    return "Sorry, I could not find the information you were looking for."


# --- UI ---

product_counts_by_country = get_product_counts_by_country(data)
st.write("### Table 1: Product counts by Country")
st.dataframe(product_counts_by_country)

nation = st.sidebar.selectbox('Select a Country (Charts 2 & 5)', product_counts_by_country.index)

top5_products = get_top_5_products_by_country(data, nation)
if not top5_products.empty:
    fig, ax = plt.subplots(figsize=(6, 6))
    top5_products.set_index('Product')['Price'].plot.pie(ax=ax, autopct='%1.1f%%')
    ax.set_ylabel('')
    st.pyplot(fig)
    st.write(f"**Piechart 2:** Top 5 Products sold in {nation} and their Price")
else:
    st.write(f"No product data available for {nation}.")

top_100_products = get_top_100_products_by_price(data)
st.write("### Table 3: Top 100 Products by Price and Countries where they are sold")
st.dataframe(top_100_products)

country_sales_info = get_country_sales_info(data)
st.write("### Table 4: Country Sales Info")
st.dataframe(country_sales_info)

selected_nation2 = st.sidebar.selectbox('Currency denomination (Chart 5)', country_sales_info['Country'].unique())
top5_by_rating = get_top_5_products_by_rating(data, selected_nation2)
if not top5_by_rating.empty:
    fig2, ax2 = plt.subplots(figsize=(6, 6))
    top5_by_rating.set_index('Product')['Rating'].plot.pie(ax=ax2, autopct='%1.1f%%')
    ax2.set_ylabel('')
    st.pyplot(fig2)
    st.write(f"**Piechart 5:** Top 5 Products by Rating for {selected_nation2}")
else:
    st.write(f"No rating data available for {selected_nation2}.")

st.write("### Chatbot")
with st.form(key='chat_form'):
    input_value = st.text_input('Ask a question', 'help')
    submitted = st.form_submit_button(label='Submit')
if submitted and input_value:
    result = get_query_results(input_value)
    st.write(result)
from sheets.sheets_api import GoogleSheetsManager
from typing import List
sheets_manager = GoogleSheetsManager('YOUR_SHEET_ID')

def read_column_values(column: str):
  return [row[0] for row in sheets_manager.read_range(f'data!{column}2:{column}100')]

def write_column_values(column: str, values: List[float]):
  sheets_manager.edit_range(f'data!{column}2:{column}100', [[value] for value in values])

def get_crypto_symbols():
  return read_column_values('A')

def write_crypto_prices(prices: List[float]):
  write_column_values('B', prices)

def get_exchange_symbols():
  return read_column_values('D')

def write_exchange_values(prices: List[float]):
  write_column_values('E', prices)

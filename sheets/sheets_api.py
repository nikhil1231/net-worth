import os
import json
from typing import Optional, List, Dict, Any
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pickle


class GoogleSheetsManager:
  """
  A class to manage Google Sheets operations including authentication,
  reading, and editing cells.
  """

  # If modifying these scopes, delete the file token.pickle.
  SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

  def __init__(self, sheet_id: str, credentials_file: str = 'credentials.json'):
    """
    Initialize the Google Sheets manager.

    Args:
      sheet_id (str): The ID of the spreadsheet
      credentials_file (str): Path to the credentials JSON file from Google Cloud Console
    """
    self.sheet_id = sheet_id
    self.credentials_file = credentials_file
    self.service = None
    self.authenticate()

  def authenticate(self) -> None:
    """
    Authenticate with Google Sheets API using OAuth 2.0.
    Creates or loads token.pickle for storing credentials.
    """
    creds = None

    # The file token.pickle stores the user's access and refresh tokens,
    # and is created automatically when the authorization flow completes for the first time.
    if os.path.exists('token.pickle'):
      with open('token.pickle', 'rb') as token:
        creds = pickle.load(token)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
      if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
      else:
        if not os.path.exists(self.credentials_file):
          raise FileNotFoundError(
            f"Credentials file '{self.credentials_file}' not found. "
            "Please download it from Google Cloud Console."
          )

        flow = InstalledAppFlow.from_client_secrets_file(
          self.credentials_file, self.SCOPES)
        creds = flow.run_local_server(port=0)

      # Save the credentials for the next run
      with open('token.pickle', 'wb') as token:
        pickle.dump(creds, token)

    self.service = build('sheets', 'v4', credentials=creds)

  def get_sheet_info(self) -> Dict[str, Any]:
    """
    Get information about a spreadsheet.

    Args:
      spreadsheet_id (str): The ID of the spreadsheet (from URL)

    Returns:
      Dict containing spreadsheet information
    """
    try:
      spreadsheet = self.service.spreadsheets().get(
        spreadsheetId=self.sheet_id
      ).execute()
      return spreadsheet
    except HttpError as error:
      print(f"An error occurred: {error}")
      return {}

  def read_cell(self, range_name: str) -> Optional[str]:
    """
    Read a single cell from a Google Sheet.

    Args:
      spreadsheet_id (str): The ID of the spreadsheet
      range_name (str): The range to read (e.g., 'Sheet1!A1')

    Returns:
      The cell value as string, or None if error
    """
    try:
      result = self.service.spreadsheets().values().get(
        spreadsheetId=self.sheet_id,
        range=range_name
      ).execute()

      values = result.get('values', [])
      if values:
        return str(values[0][0]) if values[0] else ""
      return ""

    except HttpError as error:
      print(f"An error occurred: {error}")
      return None

  def edit_cell(self, range_name: str, value: Any) -> bool:
    """
    Edit a single cell in a Google Sheet.

    Args:
      spreadsheet_id (str): The ID of the spreadsheet
      range_name (str): The range to edit (e.g., 'Sheet1!A1')
      value: The value to write to the cell

    Returns:
      bool: True if successful, False otherwise
    """
    try:
      body = {
        'values': [[value]]
      }

      result = self.service.spreadsheets().values().update(
        spreadsheetId=self.sheet_id,
        range=range_name,
        valueInputOption='RAW',
        body=body
      ).execute()

      print(f"Updated {result.get('updatedCells')} cells")
      return True

    except HttpError as error:
      print(f"An error occurred: {error}")
      return False

  def read_range(self, range_name: str) -> Optional[List[List[Any]]]:
    """
    Read a range of cells from a Google Sheet.

    Args:
      spreadsheet_id (str): The ID of the spreadsheet
      range_name (str): The range to read (e.g., 'Sheet1!A1:C10')

    Returns:
      List of lists containing the cell values, or None if error
    """
    try:
      result = self.service.spreadsheets().values().get(
        spreadsheetId=self.sheet_id,
        range=range_name
      ).execute()

      return result.get('values', [])

    except HttpError as error:
      print(f"An error occurred: {error}")
      return None

  def edit_range(self, range_name: str, values: List[List[Any]]) -> bool:
    """
    Edit a range of cells in a Google Sheet.

    Args:
      spreadsheet_id (str): The ID of the spreadsheet
      range_name (str): The range to edit (e.g., 'Sheet1!A1:C10')
      values: 2D list of values to write

    Returns:
      bool: True if successful, False otherwise
    """
    try:
      body = {
        'values': values
      }

      result = self.service.spreadsheets().values().update(
        spreadsheetId=self.sheet_id,
        range=range_name,
        valueInputOption='RAW',
        body=body
      ).execute()

      print(f"Updated {result.get('updatedCells')} cells")
      return True

    except HttpError as error:
      print(f"An error occurred: {error}")
      return False


def main():
  """
  Example usage of the GoogleSheetsManager class.
  """
  # Example spreadsheet ID (replace with your actual spreadsheet ID)
  SPREADSHEET_ID = 'your_spreadsheet_id_here'

  # Initialize the sheets manager
  try:
    sheets_manager = GoogleSheetsManager()

    # Example: Read a cell
    print("Reading cell A1...")
    cell_value = sheets_manager.read_cell(SPREADSHEET_ID, 'Sheet1!A1')
    print(f"Current value in A1: {cell_value}")

    # Example: Edit a cell
    print("\nEditing cell A1...")
    success = sheets_manager.edit_cell(SPREADSHEET_ID, 'Sheet1!A1', 'Hello from Python!')
    if success:
      print("Successfully updated cell A1")

    # Example: Read the updated cell
    print("\nReading updated cell A1...")
    updated_value = sheets_manager.read_cell(SPREADSHEET_ID, 'Sheet1!A1')
    print(f"Updated value in A1: {updated_value}")

    # Example: Read a range
    print("\nReading range A1:C3...")
    range_values = sheets_manager.read_range(SPREADSHEET_ID, 'Sheet1!A1:C3')
    if range_values:
      print("Range values:")
      for row in range_values:
        print(row)

    # Example: Edit a range
    print("\nEditing range A2:C2...")
    new_values = [['Value 1', 'Value 2', 'Value 3']]
    success = sheets_manager.edit_range(SPREADSHEET_ID, 'Sheet1!A2:C2', new_values)
    if success:
      print("Successfully updated range A2:C2")

  except FileNotFoundError as e:
    print(f"Error: {e}")
    print("\nTo set up Google Sheets API:")
    print("1. Go to Google Cloud Console (https://console.cloud.google.com/)")
    print("2. Create a new project or select existing one")
    print("3. Enable Google Sheets API")
    print("4. Create credentials (OAuth 2.0 Client ID)")
    print("5. Download the credentials JSON file")
    print("6. Rename it to 'credentials.json' and place it in this directory")
  except Exception as e:
    print(f"An error occurred: {e}")


if __name__ == "__main__":
  main()

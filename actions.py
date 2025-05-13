import io
import sys
from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright
import os
from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
SHEET_NAME = os.getenv('SHEET_NAME')

def add_transaction(sheet, service, date: str, category: str, amount: float, notes: str, person: str, account: str) -> bool:
    valid_categories = ["Income", "Expense", "Account Transfer"]
    if category not in valid_categories:
        raise ValueError(f"Category must be one of {valid_categories}")
    
    # row data to be inserted
    values = [[date, category, str(amount), notes, person, account]]
    
    request_body = {
        'requests': [
            {
                'insertDimension': {
                    'range': {
                        'sheetId': 0,
                        'dimension': 'ROWS',
                        'startIndex': 7, 
                        'endIndex': 8   
                    }
                }
            }
        ]
    }
    
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body=request_body
        ).execute()
        
        result = sheet.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f'{SHEET_NAME}!A8', 
            valueInputOption='RAW',
            body={'values': values}
        ).execute()
        
        print(f'Transaction added successfully: {result.get("updatedCells")} cells updated.')
        return True
        
    except Exception as e:
        print(f"Error adding transaction: {str(e)}")
        return False

async def list_transactions(sheet, service, head: int = None, tail: int = None) -> bool:
    try:
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f'{SHEET_NAME}!A7:F{7 + head}'  
        ).execute()
        
        values = result.get('values', [])
        if not values:
            return "No data found in the sheet."
        
        data = await markdown_to_image(values)
        output_path = 'transactions.png'
        with open(output_path, 'wb') as file:
            file.write(data)
                
        return True
      
    except Exception as e:
        print(f"Error listing transactions: {str(e)}")
        return False
        
def _abbreviate_values(values: list[list[str]]) -> None:
    for row in range(len(values)):
        for col in range(len(values[row])):
            if len(values[row][col]) > 35:
                values[row][col] = values[row][col][:33] + "..."

def list_balance(sheet, service) -> str:
    output = io.StringIO()
    original_stdout = sys.stdout
    sys.stdout = output
    
    try:
        # get values from B2:H4
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f'{SHEET_NAME}!B3:H4'
        ).execute()
        
        values = result.get('values', [])
        if not values:
            print("No balance data found.")
            return
        
        # print with numbers right-aligned
        max_label_length = max(len(str(label)) for label in values[0])
        
        for col in range(len(values[0]) - 1):
            label = values[0][col]
            amount = values[1][col]
            print(f'{label:<{max_label_length}} {amount:>10}')
        print(f'\n{"Total":<{max_label_length}} {values[1][-1]:>10}')
        
        # Capture and return the output
        printed_output = output.getvalue()
        return printed_output
        
    except Exception as e:
        return f"Error fetching balance data: {str(e)}"
        
    finally:
        # Restore the original stdout and close the string buffer
        sys.stdout = original_stdout
        output.close()

def _construct_html(table_values: list[list[str]]) -> str:
    headers = ""
    for header in table_values[0]:
        headers += f'<th> {header} </th>'
    headers = f"<tr> {headers} </tr>"
        
    body = ""
    for row in table_values[1:]:
        row_data = f""
        for col in row:
            row_data += f"<td> {col} </td>"
        row_data = f"<tr> {row_data} </tr>"
        body += row_data
    
    table = f"""
    <table>
        <thead>
            {headers}
        </thead>
        <tbody>
            {body}
        </tbody>
    </table>
    """
        
    full_html = f"""
    <html>
        <head>
            <style>
                body {{ 
                    background-color: #0E1117; 
                    padding: 0; margin: 0; width: 100vw; height: 100vh; 
                    display: flex; justify-content: center; 
                    font-family: BlinkMacSystemFont; color: white; 
                }}
                table {{ 
                    width: 97%; height: 95%; border-collapse: collapse; 
                    margin-top: 10px;
                    margin-bottom: 10px;
                }}
                th, td {{ 
                    border: 1px solid #3C444D; 
                    padding: 10px 10px; 
                }}
                tr:nth-child(odd) {{
                    background-color: #0E1117; 
                }}
                th {{ 
                    background-color: #151B23; 
                }}
                tr:nth-child(even) {{
                    background-color: #151B23; 
                }}
            </style>
        </head>
        <body>
            {table}
        </body>
    </html>
        """
    return full_html

async def markdown_to_image(table_values: list[list[str]]) -> bytes:
    _abbreviate_values(table_values)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        full_html = _construct_html(table_values)
        
        screenshot_height = (len(table_values)) * 57
        
        await page.set_content(full_html)
        await page.set_viewport_size({"width": 800, "height": screenshot_height})  # Specify your desired width and height

        try:
            await page.wait_for_load_state('networkidle')
            await page.evaluate("window.devicePixelRatio = 2") 
            screenshot = await page.screenshot()
            print(f"Screenshot captured, size: {len(screenshot)} bytes")
        except Exception as e:
            print(f"Screenshot error: {str(e)}")
            raise
        finally:
            await browser.close()
            
        return screenshot


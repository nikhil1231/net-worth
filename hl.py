import requests
from bs4 import BeautifulSoup
from util import get_env_var
import json
import os

HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
  'Accept': '*/*',
  'Accept-Encoding': 'gzip, deflate, br, zstd',
  'Accept-Language': 'en-US,en;q=0.9',
  'Cache-Control': 'no-cache',
}

FORM_HEADERS = HEADERS.copy()
FORM_HEADERS['Content-Type'] = 'application/x-www-form-urlencoded'

COOKIES_FILE = './tmp/cookies.json'

def get_holdings():
  session = login()

  res = session.get('https://online.hl.co.uk/my-accounts/account_summary/account/22', headers=HEADERS)

  holdings = parse_holdings(res.text)

  return holdings

def login():
  session = requests.Session()

  if _load_cookies(session) and is_authed(session):
    print("is authed, using saved cookies")
    return session

  print("not authed")

  step_one_html = login_step_one(session)
  login_step_two(session, step_one_html)

  _save_cookies(session)

  return session


def parse_holdings(html):
  soup = BeautifulSoup(html, 'html.parser')

  with open('./tmp/account.html', 'w') as f:
    f.write(html)

  table = soup.find('table', id='holdings-table')

  table_rows = table.find('tbody').find_all('tr')

  return [parse_holdings_row(row) for row in table_rows]

def parse_holdings_row(row):
  cells = row.find_all('td')

  ticker = cells[0].get_text(strip=True)
  stock_name = cells[1].find("span", class_="text-bold").get_text(strip=True)
  units = cells[2].get_text(strip=True)
  price_pence = cells[3].get_text(strip=True)
  value_gbp = cells[4].get_text(strip=True)
  cost_gbp = cells[5].get_text(strip=True)
  yield_percent = cells[6].get_text(strip=True)
  day_change_pence = cells[7].find_all("span")[0].get_text(strip=True)
  day_change_percent = cells[7].find_all("span")[1].get_text(strip=True)
  day_gainloss_gbp = cells[8].find_all("span")[0].get_text(strip=True)
  day_gainloss_percent = cells[8].find_all("span")[1].get_text(strip=True)
  overall_gainloss_gbp = cells[9].find_all("span")[0].get_text(strip=True)
  overall_gainloss_percent = cells[9].find_all("span")[1].get_text(strip=True)
  stock_type = cells[11].get_text(strip=True)

  floatify = lambda s: float(s.replace(',', ''))

  return {
    "ticker": ticker,
    "stock_name": stock_name,
    "units": floatify(units),
    "price_pence": floatify(price_pence),
    "value_gbp": floatify(value_gbp),
    "cost_gbp": floatify(cost_gbp),
    "overall_gainloss_gbp": floatify(overall_gainloss_gbp),
    "overall_gainloss_percent": floatify(overall_gainloss_percent),
    "yield_percent": floatify(yield_percent),
    "day_change_pence": floatify(day_change_pence),
    "day_change_percent": floatify(day_change_percent),
    "day_gainloss_gbp": floatify(day_gainloss_gbp),
    "day_gainloss_percent": floatify(day_gainloss_percent),
    "stock_type": stock_type
  }

def login_step_one(session):
  res = session.get('https://online.hl.co.uk/my-accounts/login-step-one', headers=HEADERS)
  hl_vt = _find_hl_vt(res.text)

  data = {
    'hl_vt': hl_vt,
    'username': get_env_var('HL_USERNAME'),
    'date-of-birth': get_env_var('HL_DOB'),
  }
  res = session.post('https://online.hl.co.uk/my-accounts/login-step-one', headers=FORM_HEADERS, data=data)

  return res.text

def login_step_two(session, step_one_html):
  soup = BeautifulSoup(step_one_html, 'html.parser')
  hl_vt = _find_hl_vt(step_one_html)

  secure_number = get_env_var('HL_SECURE_NUMBER')

  # Find which digits are required
  digit_labels = soup.find_all('div', class_='secure-number-container__label')
  digit_indices = [int(lab.get_text(strip=True)[0]) for lab in digit_labels]

  data = {
    'hl_vt': hl_vt,
    'online-password-verification': get_env_var('HL_PASSWORD'),
    'submit': 'Log in',
  }
  for i, idx in enumerate(digit_indices):
    data[f'secure-number[{i+1}]'] = secure_number[idx-1]

  res = session.post('https://online.hl.co.uk/my-accounts/login-step-two', headers=FORM_HEADERS, data=data)
  print(res.status_code)
  return res.text

def get_user(session):
  res = session.get('https://online.hl.co.uk/ajaxx/user.php?method=getPersonalDetails&field=client_id&format=json', headers=HEADERS)
  return res.json()

def is_authed(session):
  user = get_user(session)
  return user['client_id'] != False

def _load_cookies(session):
  if not os.path.exists(COOKIES_FILE):
    return False

  with open(COOKIES_FILE, 'r') as f:
    cookies = json.load(f)
    for k, v in cookies.items():
      session.cookies.set(k, v)
  return True

def _save_cookies(session):
  os.makedirs(os.path.dirname(COOKIES_FILE), exist_ok=True)
  with open(COOKIES_FILE, 'w') as f:
    json.dump(session.cookies.get_dict(), f)

def _find_hl_vt(html):
  soup = BeautifulSoup(html, 'html.parser')
  hl_vt_input = soup.find('input', {'name': 'hl_vt'})
  hl_vt = hl_vt_input['value'] if hl_vt_input else None
  return hl_vt

if __name__ == '__main__':
  session = login()
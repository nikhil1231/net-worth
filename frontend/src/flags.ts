const CODES: Record<string, string> = {
  'United States': 'US', 'United Kingdom': 'GB', Canada: 'CA', Japan: 'JP', France: 'FR', Germany: 'DE',
  Switzerland: 'CH', Netherlands: 'NL', Australia: 'AU', Sweden: 'SE', Denmark: 'DK', Spain: 'ES',
  Italy: 'IT', Ireland: 'IE', Belgium: 'BE', Finland: 'FI', Norway: 'NO', Austria: 'AT', Portugal: 'PT',
  Israel: 'IL', Singapore: 'SG', 'Hong Kong': 'HK', 'New Zealand': 'NZ', Luxembourg: 'LU', Taiwan: 'TW',
  'South Korea': 'KR', China: 'CN', India: 'IN', Brazil: 'BR', 'South Africa': 'ZA', 'Saudi Arabia': 'SA',
  Mexico: 'MX', Poland: 'PL', 'United Arab Emirates': 'AE', Thailand: 'TH', Malaysia: 'MY', Indonesia: 'ID',
  Qatar: 'QA', Kuwait: 'KW', Philippines: 'PH', Chile: 'CL', Turkey: 'TR', Greece: 'GR', Peru: 'PE',
  Hungary: 'HU', 'Czech Republic': 'CZ', Colombia: 'CO', Egypt: 'EG', Russia: 'RU', Argentina: 'AR',
  Bermuda: 'BM', 'Cayman Islands': 'KY', Jersey: 'JE', Guernsey: 'GG', Macau: 'MO', Vietnam: 'VN',
}

export function flag(country: string) {
  if (country === 'Cash') return '💷'
  if (country === 'Other') return '🌍'
  if (country === 'Unknown') return '❔'
  const code = CODES[country]
  if (!code) return '🏳️'
  return String.fromCodePoint(...[...code].map(c => 0x1f1e6 + c.charCodeAt(0) - 65))
}

const SECTOR_EMOJI: Record<string, string> = {
  'Information Technology': '💻', Financials: '🏦', 'Consumer Discretionary': '🛍️', 'Consumer Staples': '🛒',
  Industrials: '🏭', 'Health Care': '🩺', Materials: '⛏️', Energy: '⚡', Utilities: '💡',
  'Real Estate': '🏘️', 'Communication Services': '📡', Cash: '💷', Other: '🧩', Unknown: '❔',
}

const SECTOR_SHORT: Record<string, string> = {
  'Information Technology': 'Tech', 'Consumer Discretionary': 'Discretionary', 'Consumer Staples': 'Staples',
  'Communication Services': 'Comms',
}

export const sectorShort = (sector: string) => SECTOR_SHORT[sector] ?? sector

export const sectorEmoji = (sector: string) => SECTOR_EMOJI[sector] ?? '🧩'

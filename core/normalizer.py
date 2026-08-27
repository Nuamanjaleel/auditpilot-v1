import re
from datetime import datetime
from typing import Optional


def normalize_invoice_number(inv_no: Optional[str]) -> str:
    """
    Strips special characters, spaces, leading zeros, and converts to uppercase.
    Examples:
        'INV-2024/001'  -> 'INV20241'
        '  inv 002  '   -> 'INV2'
        '000123'        -> '123'
        'PT/24-25/99'   -> 'PT242599'
    """
    if not inv_no or not isinstance(inv_no, str):
        return ""
    
    # 1. Convert to uppercase and strip outer whitespace
    cleaned = inv_no.strip().upper()
    
    # 2. Remove all non-alphanumeric characters (spaces, dashes, slashes, etc.)
    cleaned = re.sub(r'[^A-Z0-9]', '', cleaned)
    
    # 3. Strip leading zeros for numeric-heavy invoice numbers (e.g. 000123 -> 123)
    # But keep at least one '0' if the string is just '0'
    cleaned = cleaned.lstrip('0') or '0'
    
    return cleaned


def normalize_gstin(gstin: Optional[str]) -> str:
    """
    Validates and cleans a 15-character Indian GSTIN.
    Example:
        ' 27aabcs1234f1z5 ' -> '27AABCS1234F1Z5'
    """
    if not gstin or not isinstance(gstin, str):
        return ""
    
    cleaned = gstin.strip().upper()
    # Remove any internal spaces or accidental dashes
    cleaned = re.sub(r'[^A-Z0-9]', '', cleaned)
    
    return cleaned


def normalize_date(date_val) -> Optional[datetime]:
    """
    Parses various date formats from GSTR-2B and Tally into a standard datetime object.
    Supports formats like:
        '15-06-2024', '15-Jun-2024', '2024-06-15', '15/06/2024', Excel Timestamps
    """
    if date_val is None:
        return None
    
    if isinstance(date_val, datetime):
        return date_val
    
    date_str = str(date_val).strip()
    if not date_str or date_str.lower() == 'nan':
        return None
    
    # Common date formats used in Indian accounting & GST
    formats = [
        '%d-%m-%Y', '%d-%b-%Y', '%d-%B-%Y',
        '%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y',
        '%d-%m-%y', '%Y/%m/%d', '%d.%m.%Y',
        '%Y-%m-%d %H:%M:%S'
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
            
    return None


def normalize_amount(amount_val) -> float:
    """
    Converts Indian currency strings and floats to standard float values.
    Examples:
        '1,18,000.50' -> 118000.50
        '₹ 50,000'    -> 50000.0
        None / NaN    -> 0.0
    """
    if amount_val is None:
        return 0.0
    
    if isinstance(amount_val, (int, float)):
        import math
        return 0.0 if math.isnan(amount_val) else round(float(amount_val), 2)
    
    amt_str = str(amount_val).strip()
    if not amt_str or amt_str.lower() in ('nan', 'none', '-'):
        return 0.0
    
    # Remove Indian Rupee symbols, commas, and spaces
    amt_str = amt_str.replace('₹', '').replace(',', '').replace(' ', '')
    
    try:
        return round(float(amt_str), 2)
    except ValueError:
        return 0.0